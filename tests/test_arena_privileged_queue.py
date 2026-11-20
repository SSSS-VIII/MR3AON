"""Changing a model cannot repeatedly starve untouched boards in full coverage."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_batch import pending_cases
import arena_privileged_batch as batch
import pytest


def inventory():
    cases={key:dict(key=key,kind='ordinary',level=5,slot=1,
                   unimplemented_enemy_classes=[],unbound_enemy_ids=[])
           for key in ('first','untouched','passed')}
    ledger={key:dict(nominal_complete=False,attempts=[]) for key in cases}
    ledger['first']['attempts']=[dict(revision='old',finished_at=1)]
    ledger['passed'].update(nominal_complete=True,attempts=[dict(revision='old',finished_at=2)])
    return cases,ledger


def test_new_revision_covers_new_contexts_before_retrying_old_failures():
    cases,ledger=inventory()
    assert [c['key'] for c in pending_cases(cases,ledger,'new')]==['untouched','first']
    assert [c['key'] for c in pending_cases(cases,ledger,'old')]==['untouched']


def test_explicit_research_target_can_still_override_coverage_order():
    cases,ledger=inventory()
    assert [c['key'] for c in pending_cases(cases,ledger,'new',['first','first'])]==['first','untouched']


def test_fresh_certificate_precedes_coverage_and_does_not_repeat_a_finished_check():
    cases,ledger=inventory()
    assert [c['key']for c in pending_cases(cases,ledger,'new',certify_cases=['passed'])]==['passed','untouched','first']
    ledger['passed']['attempts'].append(dict(revision='new',finished_at=3,certification_requested=False))
    assert pending_cases(cases,ledger,'new',certify_cases=['passed'])[0]['key']=='passed'
    ledger['passed']['attempts'].append(dict(revision='new',finished_at=4,certification_requested=True))
    assert [c['key']for c in pending_cases(cases,ledger,'new',certify_cases=['passed'])]==['untouched','first']
    ledger['passed']['timing_robust']=True
    assert [c['key']for c in pending_cases(cases,ledger,'next',certify_cases=['passed'])]==['untouched','first']


def test_unsuccessful_fresh_search_keeps_prior_candidate_and_certification_separate():
    item=dict(nominal_complete=True,timing_robust=False,nominal_candidate='old')
    attempt=dict(output='new');result=dict(status='wall_budget',nominal_complete=False,timing_robust=False,
        wall_seconds=300.,game_seconds=4.,backtracks=20)
    batch.record_result(item,attempt,result)
    assert item['nominal_complete'] and item['nominal_candidate']=='old' and not item['timing_robust']
    assert not attempt['nominal_complete']
    result.update(status='native_endpoints_passed',nominal_complete=True,timing_robust=True)
    batch.record_result(item,attempt,result)
    assert item['nominal_candidate']==item['timing_candidate']=='new' and item['timing_robust']


def test_startup_diagnostics_are_bounded_and_cannot_use_root_rpc_after_game_gate():
    from types import SimpleNamespace
    class VM:
        arena_game_gate=True
        def __init__(self):
            self.commands=[]
            self.session=SimpleNamespace(spec=SimpleNamespace(name='arena-search'))
        def command(self,command,timeout):
            self.commands.append(command)
            return dict(exit_code=0,text='1234\n'if command.startswith('pidof')else 'queued')
    vm=VM()
    assert batch.bootstrap_diagnostics(vm)==dict(available=False,reason='game_gate_already_armed')
    assert not vm.commands
    vm.arena_game_gate=False
    result=batch.bootstrap_diagnostics(vm)
    assert result['pid']=='1234' and result['files']['native-agent-status.txt']=='queued'
    assert len(vm.commands)==6 and all('head -c 4096'in c for c in vm.commands[1:])


def test_numeric_early_board_order_avoids_travelling_to_tenth_before_second():
    keys=('L5-M41-S10-B5109','L5-M41-S2-B5102','L5-M41-S5-B51052')
    cases={key:dict(key=key,slot=slot,kind='ordinary',level=5,
                    unimplemented_enemy_classes=[],unbound_enemy_ids=[])
           for key,slot in zip(keys,(10,2,5))}
    ledger={key:dict(nominal_complete=False,attempts=[]) for key in keys}
    assert [c['slot'] for c in pending_cases(cases,ledger,'new')]==[2,5,10]


def test_entry_timeout_can_continue_only_after_complete_native_restore(monkeypatch):
    class Gate:
        uncertain_operation=None
        def __init__(self):self.vm=self;self.state=dict(health=5000);self.points={}
        def call(self,op):return self.state.copy()
        def snapshot(self):self.points[1]=self.state.copy();return dict(result=dict(id=1))
        def restore(self,point):self.state=self.points[point].copy()
        def drop(self,point):del self.points[point]
    def failed(gate,*args,**kwargs):
        gate.state['health']=0
        raise TimeoutError('Original selection did not finish')
    monkeypatch.setattr(batch,'initialize',failed);gate=Gate()
    with pytest.raises(batch.EntryTimeoutRestored):batch.initialize_case(gate,{},lambda r:None,1)
    assert gate.state==dict(health=5000) and not gate.points
    gate=Gate();gate.uncertain_operation='unacknowledged_restore'
    with pytest.raises(TimeoutError):batch.initialize_case(gate,{},lambda r:None,1)
    assert gate.state['health']==0 and gate.points


@pytest.mark.parametrize('budget,timeout',((600,900),(1800,1920)))
def test_selection_watchdog_and_host_wait_share_the_software_guest_budget(monkeypatch,budget,timeout):
    native=sys.modules[batch.initialize.__module__];calls=[]
    monkeypatch.setattr(native,'native_call',lambda gate,code,progress,timeout:
                        calls.append(dict(code=code,timeout=timeout)))
    class Gate:
        def snapshot(self):return dict(result=dict(id=1))
        def call(self,op,**kwargs):
            if op=='state':return dict(state='Game: 8',content='Running: 1',health=5000)
            return dict(map=42,stage_id=50012,stage_index=0,god=False,mounted=False)
    gate=Gate()
    if budget!=600:gate.selection_wall_seconds=budget
    result=native.initialize(gate,dict(selection=dict(map=42),map=42,stage=50012,slot=1),lambda r:None)
    assert 'return MR3A.native_select({["map"]=42},55200,'+str(budget)+')' in calls[0]['code']
    assert calls[0]['timeout']==timeout and result['continued_steps']==0
