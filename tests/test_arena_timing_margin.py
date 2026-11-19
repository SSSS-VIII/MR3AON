"""Timing uses the engine clock, real prefixes, and actual action prerequisites."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab'))
from timing_margin import verify
from endpoint_rollout import scenarios


class Oracle:
    def __init__(self,slow_landing=False,damage=False):
        self.data=dict(render=0,x=0.,hp=5000,phase='runOnLine: 1',ready=None,target=None)
        self.points={};self.sequence=0;self.slow=slow_landing;self.damage=damage;self.max_points=0
    def state(self):
        d=self.data
        return dict(frame=d['render'],time=d['render']/60,episodeFrame=d['render']*5//6,
                    health=d['hp'],physics=d['phase'],position=dict(x=d['x'],y=.75),speed=18)
    def board(self):return dict(map=42,stage_index=int(self.data['x']>=22))
    def call(self,op,**_):return self.state()if op=='state'else self.board()
    def snapshot(self):
        self.sequence+=1;self.points[self.sequence]=deepcopy(self.data)
        self.max_points=max(self.max_points,len(self.points));return dict(result=dict(id=self.sequence))
    def restore(self,p):self.data=deepcopy(self.points[p]);return dict(ms=1)
    def drop(self,p):del self.points[p]
    def render_step(self,frames,action='none'):
        before=self.state();d=self.data
        if action=='down'and d['phase']=='runOnLine: 1':
            d.update(phase='rollToLineDown: 3',ready=d['render']+(18 if self.slow else 7),target='runOnLineDown: 2')
        if action=='jump'and d['phase']=='runOnLineDown: 2':
            d.update(phase='rollToLineOn: 4',ready=d['render']+3,target='runOnLine: 1')
        samples=[]
        for _ in range(frames):
            d['render']+=1;d['x']+=.3
            if d['ready']is not None and d['render']>=d['ready']:
                d['phase']=d['target'];d['ready']=None
            if self.damage and d['x']>=17:d['hp']=4750
            samples.append(self.state())
        return dict(before=before,after=self.state(),done=True,samples=samples,board=self.board(),unit='unity_render_frame')


def baseline(oracle):
    initial=oracle.snapshot()['result']['id'];state=oracle.state();rows=[]
    for i in range(30):
        action='down'if i==6 else'jump'if i==12 else'none'
        job=oracle.render_step(3,action)
        rows.append(dict(job=job,action=action,ticks=job['after']['episodeFrame']-job['before']['episodeFrame'],
                         point=oracle.snapshot()['result']['id']))
    return dict(initial_point=initial,initial_state=state,rows=rows,
                start=dict(health=5000,board=dict(map=42,stage_index=0)),board_code='board')


def test_engine_time_endpoints_keep_each_physical_prefix_and_restore_the_parked_vm():
    oracle=Oracle();args=baseline(oracle);park=deepcopy(oracle.data);points=set(oracle.points)
    result=verify(oracle,whole_board=True,**args)
    assert result['passed']and result['version']==2 and result['offsets_ms']==[-40,40]
    assert result['clock']=='Unity.Time.time'and result['exhaustive']is False
    assert oracle.data==park and set(oracle.points)==points
    assert {tuple(c['schedule'])for c in result['checks']}=={tuple(p['schedule'])for p in scenarios((0,1))}
    for check in result['checks']:
        for key,offset in zip(check['actions'],check['schedule']):
            assert key['requested_shift_ms']==offset
            assert key['actual_shift_ms']==pytest.approx(50 if offset==40 else-50 if offset==-40 else 0)
    assert any(c['schedule']==[40,-40]for c in result['checks'])


def test_delayed_landing_is_not_replaced_by_the_next_keys_nominal_contact_state():
    oracle=Oracle(slow_landing=True);args=baseline(oracle);park=deepcopy(oracle.data)
    result=verify(oracle,whole_board=True,**args)
    assert not result['passed']
    failure=result['failure']
    assert failure['reason']=='operation_prerequisite_mismatch'
    assert failure['event']['index']==1 and failure['actual']['physics']=='rollToLineDown: 3'
    assert failure['perturbed_event']['index']==0 and failure['repair_row_index']==6
    assert failure['actual']['health']==5000  # Reject ignored actions before a hit.
    assert oracle.data==park


def test_an_early_endpoint_cannot_be_claimed_before_the_retained_entry():
    oracle=Oracle();args=baseline(oracle)
    args['rows'][0]['action']='down'
    args['rows'][0]['job']['after']['physics']='rollToLineDown: 3'
    args['rows']=args['rows'][:1]
    result=verify(oracle,**args)
    assert not result['passed']
    assert result['failure']['reason']=='earlier_side_precedes_reachable_prefix'


def test_damage_in_counterfactual_probe_is_not_hidden_by_restoring_an_early_point():
    oracle=Oracle();args=baseline(oracle);oracle.damage=True
    result=verify(oracle,whole_board=True,**args)
    assert not result['passed']and result['failure']['reason']=='native_damage'
    assert oracle.data['hp']==5000


def test_nominal_input_with_no_effect_is_not_accepted_as_a_successful_key():
    oracle=Oracle();args=baseline(oracle)
    row=args['rows'][6];row['job']['after']['physics']=row['job']['before']['physics']
    result=verify(oracle,**args)
    assert not result['passed']and result['failure']['reason']=='nominal_operation_has_no_effect'


def test_different_game_counter_phase_does_not_change_the_measured_window():
    class DifferentCounter(Oracle):
        def state(self):
            s=super().state();s['episodeFrame']=(s['frame']*5+3)//6
            return s
    oracle=DifferentCounter();result=verify(oracle,whole_board=True,**baseline(oracle))
    assert result['passed']
    assert all(abs(a['actual_shift_ms'])==pytest.approx(50)
               for c in result['checks']for a in c['actions']if a['requested_shift_ms'])


def test_cache_bound_does_not_merge_different_physical_prefixes_or_leak_points():
    from endpoint_rollout import Rollouts
    from timing_margin import events
    oracle=Oracle();args=baseline(oracle);keys=events(args['rows']);park=deepcopy(oracle.data)
    r=Rollouts(oracle,keys,point=args['initial_point'],state=args['initial_state'],start=args['start'],
               board_code='board',end_state=args['rows'][-1]['job']['after'],whole_board=True,cache_limit=1)
    initial_points=set(oracle.points)
    try:
        assert all(r.run(p)['passed']for p in scenarios((0,1)))
        assert len(r.cache)<=1
    finally:r.close()
    assert set(oracle.points)==initial_points
