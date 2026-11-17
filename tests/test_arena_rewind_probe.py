"""The audit must expose its limits and preserve differences that matter."""
from copy import deepcopy
import pytest

from arena_rewind_probe import canonical,differences,tick_schedule


def test_fifty_ms_targets_use_original_twenty_ms_ticks_without_drift():
    ticks=tick_schedule(20)
    assert ticks==[2,3]*10
    assert sum(ticks)*20==1000
    for i in range(1,len(ticks)+1):
        assert 0<=i*50-sum(ticks[:i])*20<20


@pytest.mark.parametrize('args',[(0,), (True,), (201,), (3,10), (3,50,0)])
def test_bad_schedules_cannot_start_a_native_probe(args):
    with pytest.raises(ValueError):tick_schedule(*args)


def test_audit_ignores_documented_engine_clocks_but_preserves_game_rng_and_seed():
    snapshot=dict(engine=dict(time=123,frame=456),state=dict(time=123,frame=456,seed=5,health=5000),
                  rng=dict(random_game=dict(values=dict(inext=3))),objects=[])
    original=deepcopy(snapshot)
    changed=deepcopy(snapshot)
    changed['engine']['time']+=20
    changed['state']['time']+=20
    assert canonical(snapshot)==canonical(changed)
    assert snapshot==original
    changed['rng']['random_game']['values']['inext']=4
    delta=differences(canonical(snapshot),canonical(changed))
    assert delta[0]['path']=='/rng/random_game/values/inext'
    changed=deepcopy(snapshot)
    changed['state']['seed']=6
    assert differences(canonical(snapshot),canonical(changed))


def test_enemy_enumeration_order_is_not_a_replay_difference():
    a=dict(objects=[dict(name='A',position=dict(x=1)),dict(name='B',position=dict(x=2))])
    b=dict(objects=list(reversed(a['objects'])))
    assert canonical(a)==canonical(b)


def test_missing_state_and_additional_objects_are_not_silently_accepted():
    delta=differences(dict(objects=[],pending='timer'),dict(objects=[1]))
    assert {r['path']for r in delta}=={'/objects/length','/pending'}
