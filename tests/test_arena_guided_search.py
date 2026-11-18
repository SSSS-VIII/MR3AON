from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab'))
import guided_search


def rows(actions,offset=0):
    return [dict(action=action,point=offset+i+1,job=dict(before=dict(
        episodeFrame=i*2,position=dict(x=float(i))),after=dict(episodeFrame=i*2+2)))
        for i,action in enumerate(actions)]


def test_future_operation_is_checked_before_committing_waits_without_banning_its_other_alternatives(monkeypatch):
    calls=[];checked=[];dropped=[]
    def searcher(gate,**kwargs):
        calls.append(kwargs)
        plan=rows(['none','none','jump'if len(calls)==1 else'down','none'],10*len(calls))
        return dict(found=True,root=10,stats=dict(trials=1),path=plan[:2],forecast_path=plan)
    def verify(gate,plan,**kwargs):
        checked.append(kwargs['selected_rows'])
        if len(checked)==1:
            return dict(passed=False,checks=[],failure=dict(reason='native_damage',
                max_world_x=2.2,event=dict(row_index=2)))
        return dict(passed=True,checks=[])
    monkeypatch.setattr(guided_search,'verify',verify)
    gate=SimpleNamespace(restore=lambda _:None,drop=dropped.append)
    result=guided_search.window(gate,searcher=searcher,history=[],initial_point=10,
        initial_state={},board_code='board',start={},max_trials=4)
    assert result['found']and checked==[{2},{2}]
    assert ('none','none','jump')in calls[1]['forbidden_prefixes']
    assert ('none','none')not in calls[1]['forbidden_prefixes']
    assert len(result['timing_attempts'])==2
    assert set(dropped)=={11,12,13,14,23,24}


def test_causal_prefix_covers_later_rows_that_can_return_to_a_reached_world_position():
    plan=rows(['none','jump','none','down','none'])
    for row,x in zip(plan,[0,1,6,2,7]):row['job']['before']['position']['x']=x
    audit=dict(failure=dict(reason='native_damage',max_world_x=2.1,event=dict(row_index=6)))
    assert guided_search.rejected_prefix(plan,5,audit)==('none','jump','none','down')
    # A timing/transport witness without an actual damage position cannot
    # justify excluding every different continuation of the same prefix.
    audit['failure'].pop('max_world_x')
    assert guided_search.rejected_prefix(plan,5,audit)==tuple(r['action']for r in plan)


def test_a_future_key_at_the_horizon_is_not_rejected_for_lacking_a_later_forecast(monkeypatch):
    def verify(*args,**kwargs):raise AssertionError('No complete later-side window is available')
    monkeypatch.setattr(guided_search,'verify',verify)
    plan=rows(['none','none','none','jump'])
    def searcher(*args,**kwargs):
        return dict(found=True,root=10,stats=dict(trials=1),path=plan[:2],forecast_path=plan)
    result=guided_search.window(SimpleNamespace(drop=lambda _:None),searcher=searcher,history=[],
        initial_point=10,initial_state={},board_code='board',start={},max_trials=2)
    assert result['found']and result['timing_attempts'][0]['operations']==0


def test_an_earlier_safe_future_key_cannot_hide_a_later_unsafe_key(monkeypatch):
    selected=[]
    plan=rows(['none','none','jump','none','down','none'])
    def searcher(*args,**kwargs):
        return dict(found=True,root=10,stats=dict(trials=1),path=plan[:2],forecast_path=plan)
    def verify(gate,rows,**kwargs):
        selected.append(kwargs['selected_rows'])
        return dict(passed=True,checks=[])
    monkeypatch.setattr(guided_search,'verify',verify)
    result=guided_search.window(SimpleNamespace(drop=lambda _:None),searcher=searcher,history=[],
        initial_point=10,initial_state={},board_code='board',start={},max_trials=2)
    assert result['found']and selected==[{2,4}]
