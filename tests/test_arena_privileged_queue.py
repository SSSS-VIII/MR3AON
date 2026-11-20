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
