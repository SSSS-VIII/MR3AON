"""Model-guided branch selection and complete host/guest causal restoration."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'tools/arena_checkpoint_lab'))
from privileged_search import restore_branch,select_alternative
from arena_privileged_policy import InternalController
from arena_privileged_catalog import dependencies
import privileged_search
from arena_privileged_policy import Proposal


def observation():
    return json.loads((ROOT/'tests/fixtures/arena-privileged-native.json').read_text())


def test_branch_restore_preserves_original_input_cooldowns_and_absolute_pending_window():
    obs=observation();controller=InternalController(collect_alternatives=True)
    controller.delivered('down',obs['state']['time']-.05)
    controller.scheduled=dict(action='jump',due=obs['state']['time']+.3,window=(1.,2.))
    saved=deepcopy(controller)
    branch=dict(point=14,controller=saved,observation=deepcopy(obs))
    class Gate:
        def restore(self,identity):
            assert identity==14
            return dict(ms=23.)
        def call(self,operation):
            assert operation=='state'
            return deepcopy(obs['state'])
    controller.delivered('jump',obs['state']['time']+12.)
    restored,state,ms=restore_branch(Gate(),branch)
    assert ms==23.
    assert restored.last_inputs==saved.last_inputs
    assert restored.scheduled==saved.scheduled
    assert restored.last_inputs!=controller.last_inputs
    restored.scheduled['due']+=1
    state['state']['time']+=1
    assert restored.scheduled!=saved.scheduled
    assert state!=branch['observation']


def test_branch_restore_refuses_native_mismatch():
    obs=observation()
    class Gate:
        def restore(self,identity):return dict(ms=3)
        def call(self,operation):return dict(obs['state'],health=4999)
    with pytest.raises(RuntimeError,match='differs'):
        restore_branch(Gate(),dict(point=1,controller=InternalController(),observation=obs))


def test_search_alternatives_are_native_model_safe_windows_not_key_enumeration():
    obs=observation();controller=InternalController(collect_alternatives=True)
    result=controller.decide(obs)
    choices=result.evidence['alternatives']
    assert len(choices)>1
    assert {c['action'] for c in choices}<= {'jump','down'}
    assert all(c['window'][1]-c['window'][0]>=.08 for c in choices)
    assert all(c['delay']<result.evidence['coast']['first_contact'] for c in choices)
    assert all(c['margin']>.025 for c in choices)
    assert result.evidence['native_rollouts']==result.evidence['restores']==0


def test_search_selected_window_has_fixed_absolute_due_time():
    obs=observation();controller=InternalController(collect_alternatives=True)
    first=controller.decide(obs);option=first.evidence['alternatives'][-1]
    select_alternative(controller,option,obs['state']['time'])
    due=controller.scheduled['due']
    later=deepcopy(obs);later['state']['time']+=.01
    result=controller.decide(later)
    assert result.reason=='approach_selected_internal_window'
    assert controller.scheduled['due']==due
    assert result.delay==pytest.approx(due-later['state']['time'])


def test_dependency_inventory_keeps_unknowns_special_cases_and_never_infers_pass():
    inventory=dict(counts=dict(unique_fixed=3,contexts=3),stages={
        '1':dict(mechanism=dict(enemy_type_counts={'101':2},item_type_counts={'53':3})),
        '2':dict(mechanism=dict(enemy_type_counts={'999':1},item_type_counts={'15':1})),
        '3':dict(mechanism=dict(enemy_type_counts={},item_type_counts={'32':1}))},
        contexts=[dict(key='one',stage=1,kind='ordinary'),dict(key='two',stage=2,kind='ordinary'),
                  dict(key='boss',stage=3,kind='boss')])
    entities=[dict(kind='enemies',type_id=101,prefabs=['blade'])]
    prefabs=dict(blade=dict(scripts=[dict(path='/Blade',class_name='EnemyBlade'),
                                    dict(path='/Blade/hurt',class_name='EnemyBaseCollider')]))
    result=dependencies(inventory,entities,prefabs)
    assert set(result['cases'])=={'one','two','boss'}
    assert result['families']['EnemyBlade']['reducer']
    assert result['cases']['two']['unbound_enemy_ids']==[999]
    assert result['cases']['boss']['kind']=='boss'
    assert not any(c['native_no_damage'] or c['timing_robust'] for c in result['cases'].values())


def test_native_injury_backtracks_to_model_alternative_and_keeps_rejected_evidence(tmp_path,monkeypatch):
    native=observation();native['state']['health']=5000;native['state']['timeScale']=0
    native['role']['god']=native['role']['mounted']=False
    start_board=dict(map=42,stage_index=0,stage_count=4,stage_start=0,stage_id=50012,god=False,mounted=False)
    class Controller:
        requested_timing_radius=.04
        timing_radius=.05
        timing_quantum=1/60
        def __init__(self,**kwargs):self.scheduled=None;self.last_inputs={}
        def decide(self,obs):
            action=self.scheduled['action'] if self.scheduled else 'jump'
            options=[dict(action=a,delay=0.,window=(0.,.1),margin=.5,first_contact=2.) for a in ('jump','down')]
            fresh=self.scheduled is None
            if fresh:select_alternative(self,options[0],obs['state']['time'])
            return Proposal(action,0.,(0.,.1),.5,'execute',dict(compute_ms=1.,alternatives=options if fresh else []))
        def delivered(self,action,stamp):self.last_inputs[action]=stamp;self.scheduled=None
    class Gate:
        def __init__(self):
            self.observation=deepcopy(native);self.board=deepcopy(start_board);self.points={};self.sequence=0;self.actions=[]
        def call(self,operation,**kwargs):
            if operation=='state':return deepcopy(self.observation['state'])
            return deepcopy(self.observation if 'privileged_state' in kwargs['code'] else self.board)
        def snapshot(self):
            self.sequence+=1;self.points[self.sequence]=(deepcopy(self.observation),deepcopy(self.board))
            return dict(result=dict(id=self.sequence))
        def restore(self,identity):
            self.observation,self.board=deepcopy(self.points[identity]);return dict(ms=3.)
        def drop(self,identity):del self.points[identity]
        def render_step(self,frames,action):
            self.actions.append(action);before=deepcopy(self.observation['state']);after=self.observation['state']
            after['time']+=.05;after['episodeFrame']+=3;after['frame']+=frames;after['position']['x']+=1.
            if action=='jump':after['health']-=100
            else:self.board['stage_index']=1
            return dict(before=before,after=deepcopy(after),done=True,samples=[deepcopy(after)],terminated=action=='jump')
    monkeypatch.setattr(privileged_search,'InternalController',Controller)
    monkeypatch.setattr(privileged_search,'observe',lambda gate:deepcopy(gate.observation))
    gate=Gate();output=tmp_path/'search'
    report=privileged_search.run(gate,output,max_decisions=4,max_backtracks=1,wall_seconds=30,certify=False)
    assert gate.actions==['jump','down']
    assert report['backtracks']==1 and report['nominal_complete']
    assert not report['timing_robust'] and not report['complete']
    assert [r['action'] for r in report['route']]==['down']
    rows=[json.loads(s) for s in (output/'decisions.jsonl').read_text().splitlines()]
    assert rows[0]['job']['after']['health']==4900
    assert rows[1]['observation']['state']['health']==5000
    assert not gate.points


def test_long_board_forward_allowance_is_separate_from_short_board_search_budget():
    from privileged_search import duration_allowance
    short=observation();short['board']=dict(finish=dict(x=short['state']['position']['x']+200))
    assert duration_allowance(short,300)['effective_wall_seconds']==300
    long=deepcopy(short);long['board']['finish']['x']+=600
    allowance=duration_allowance(long,300)
    assert 300<allowance['effective_wall_seconds']<=1800
    assert allowance['requested_wall_seconds']==300
    assert duration_allowance(long,7200)['effective_wall_seconds']==7200
    del long['board']['finish']
    assert duration_allowance(long,300)['effective_wall_seconds']==300
