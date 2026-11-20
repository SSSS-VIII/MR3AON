"""Original reset/birth/camera clocks, with historical uncertainty kept explicit."""
from copy import copy,deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import pending_hook_phase,pending_hook
from arena_privileged_model import PlayerModel,hazard_forecasts

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-hook-phase.json').read_text())


def trajectory(case):
    times=np.unique(np.r_[np.linspace(0.,1.8,217),[v['seconds']for v in case['after']]])
    model=PlayerModel(case['before']);_,motors,valid=model.trajectory(times)
    assert valid
    return times,model,motors


@pytest.mark.parametrize('case',DATA['cases'])
def test_pre_birth_forecast_contains_real_original_reset_and_later_swing(case):
    original=deepcopy(case);times,model,motors=trajectory(case)
    hs,reason=pending_hook_phase(case['entry'],times,case['before'],model,motors,{})
    assert reason is None and len(hs)==1 and 'bounded role-distance birth'in hs[0].source
    h=hs[0]
    for q in case['after']:
        i=int(np.searchsorted(times,q['seconds']));c=q['collider']
        assert h.active[i]
        points=np.array([[p[a]for a in('x','y')]for p in c['quad']])
        assert np.all(abs(points-h.centers[i])<=h.extents[i]+.0002)
    assert case==original


def test_already_observed_motor_and_identical_counterfactual_motor_cannot_share_past_birth_phase():
    case=DATA['cases'][1];times,model,motors=trajectory(case)
    before=model.initial;projected=copy(model);projected.initial=copy(before)
    assert projected.initial==before
    hs,reason=pending_hook_phase(case['entry'],times,case['before'],projected,motors,{})
    assert reason is None and hs[0].geometry=='sphere'and hs[0].active.all()
    assert 'complete pre-birth swing'in hs[0].source


@pytest.mark.parametrize('change',['parent','vertical','camera','opposite','gravity'])
def test_unproved_phase_keeps_the_valid_full_turn_shape(change):
    case=deepcopy(DATA['cases'][0]);e=case['entry'];o=case['before']
    if change=='parent':e['source']='resolved_uninstantiated_block'
    if change=='vertical':e['vertical_gate']=True
    if change=='camera':o['camera']['fields']['_cameraShift']=True
    if change=='opposite':e['custom']['_isGravityOpposite']=True
    if change=='gravity':o['spawn_templates']['hooks']['EnemyGoldHook']['gravity_acc']=0.
    times,model,motors=trajectory(case)
    hs,reason=pending_hook_phase(e,times,o,model,motors,{})
    assert reason is None and hs[0].geometry=='sphere'and hs[0].active.all()


def test_unbound_original_creation_callback_is_not_rescued_by_a_fallback_shape():
    case=deepcopy(DATA['cases'][0]);case['before']['spawn_templates']['hooks']['EnemyGoldHook']['native_spawn']=False
    times,model,motors=trajectory(case)
    hs,reason=pending_hook_phase(case['entry'],times,case['before'],model,motors,{})
    assert hs is None and reason=='pending_hook_unverified_hierarchy'


def test_counterfactual_live_hook_angle_is_not_borrowed_from_the_nominal_observation():
    case=DATA['cases'][2];o=case['before'];times,model,motors=trajectory(case)
    projected=copy(model);projected.initial=copy(model.initial)
    hs,missing=hazard_forecasts(o,times,projected,motors)
    assert not missing
    enclosed=[h for h in hs if 'counterfactual complete-turn'in h.source]
    assert enclosed
    for h in enclosed:
        enemy=next(e for e in o['enemies']if e['id']==h.enemy)
        assert np.allclose(h.centers,[[enemy['position'][a]for a in('x','y')]])
        c=next(c for c in enemy['colliders']if c['id']==h.id)
        lever=max(np.hypot(p['x']-enemy['position']['x'],p['y']-enemy['position']['y'])for p in c['quad'])
        assert h.extents.min()>=lever and h.quads is None


def test_phase_cache_reuses_only_the_same_bound_timing_window_and_never_counterfactual_history(monkeypatch):
    import arena_privileged_families as family
    case=DATA['cases'][1];times,model,motors=trajectory(case);calls=[];original=family.math.sin
    def counted(value):calls.append(1);return original(value)
    monkeypatch.setattr(family.math,'sin',counted)
    memo={};first,reason=pending_hook_phase(case['entry'],times,case['before'],model,motors,memo)
    assert not reason and calls
    count=len(calls)
    second,reason=pending_hook_phase(case['entry'],times,case['before'],model,motors,memo)
    assert not reason and second is first and len(calls)==count
    projected=copy(model);projected.initial=copy(model.initial)
    other,reason=pending_hook_phase(case['entry'],times,case['before'],projected,motors,memo)
    assert not reason and other is not first and other[0].geometry=='sphere'


def test_another_observation_cannot_inherit_a_cached_old_birth_pose():
    case=DATA['cases'][1];o=case['before'];times,model,motors=trajectory(case);memo={}
    hs,missing=hazard_forecasts(o,times,model,motors,forecast_cache=memo)
    assert not missing
    old=next(h for h in hs if h.enemy==case['entry']['id'])
    other=deepcopy(o)
    entry=next(e for e in other['pending_enemies']if e['id']==case['entry']['id'])
    entry['info']['_localEulerAngles']['z']+=30.
    next_model=PlayerModel(other);_,states,valid=next_model.trajectory(times);assert valid
    hs,missing=hazard_forecasts(other,times,next_model,states,forecast_cache=memo)
    assert not missing and memo['_observation']is other
    new=next(h for h in hs if h.enemy==entry['id'])
    assert np.max(abs(new.centers-old.centers))>.1


def reference_projection(case,offset=.2):
    times,origin,motors=trajectory(case)
    start=int(np.searchsorted(times,offset));indices=np.arange(start,len(times))
    observation=deepcopy(case['before']);elapsed=float(times[start])
    observation['state']['time']+=elapsed
    current=PlayerModel(observation);current.initial=copy(motors[start])
    current._reference_history=dict(model=origin,times=times,motors=motors,
        indices=indices,offset=elapsed)
    return times[indices]-elapsed,current,[motors[i]for i in indices],observation


def test_pending_phase_propagates_from_actual_pre_key_world_without_nominal_clock():
    case=DATA['cases'][1];whole,origin,motors=trajectory(case)
    expected,reason=pending_hook_phase(case['entry'],whole,case['before'],origin,motors,{})
    times,current,states,observation=reference_projection(case)
    # An unobserved past key must use the actual earlier world's birth clock.
    observation['camera']['right']['x']+=100.
    hs,reason=pending_hook_phase(case['entry'],times,observation,current,states,{})
    assert not reason and 'propagated from the actual pre-key world'in hs[0].source
    indices=current._reference_history['indices']
    assert np.array_equal(hs[0].active,expected[0].active[indices])
    assert np.array_equal(hs[0].centers,expected[0].centers[indices])
    assert np.array_equal(hs[0].extents,expected[0].extents[indices])


@pytest.mark.parametrize('change',['clock','query','identity','shape'])
def test_unproved_pre_key_history_cannot_narrow_pending_turn(change):
    case=deepcopy(DATA['cases'][1]);times,current,states,o=reference_projection(case)
    entry=deepcopy(case['entry'])
    if change=='clock':o['state']['time']+=.01
    if change=='query':times=times+.001
    if change=='identity':entry['info_identity']+=1
    if change=='shape':entry['info']['_localScale']['x']*=2
    hs,reason=pending_hook_phase(entry,times,o,current,states,{})
    assert not reason and hs[0].geometry=='sphere'
    assert 'complete pre-birth swing'in hs[0].source


def test_already_rotating_hook_keeps_phase_only_with_pre_key_identity():
    from arena_privileged_families import hook_rotation_precedes_counterfactual_key
    case=DATA['cases'][2];times,current,states,o=reference_projection(case)
    enemy=o['enemies'][0]
    assert hook_rotation_precedes_counterfactual_key(enemy,times,o,current)
    # Same native object ID after recycling is not a proof of the same spawn.
    enemy['fields']['m_index']+=1
    assert not hook_rotation_precedes_counterfactual_key(enemy,times,o,current)
