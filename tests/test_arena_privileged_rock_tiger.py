"""Original RockTiger head paths and continuous aim/capsule envelopes."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import planar_arc_bounds,rock_tiger
from arena_privileged_model import PlayerModel,hazard_forecasts

FIXTURE=json.loads((Path(__file__).parent/'fixtures/arena-privileged-rock-tiger.json').read_text())


@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda c:c['name'])
def test_native_idle_aim_attack_retract_and_terminal_capsule(case):
    before=case['before'];after=case['after'];enemy=before['enemies'][0]
    elapsed=after['state']['time']-before['state']['time']
    times=np.linspace(0.,elapsed,round(elapsed*120)+1)
    model=PlayerModel(before)
    _,motors,valid=model.trajectory(times,tuple(map(tuple,case.get('operations',[]))))
    assert valid
    hazards,missing=hazard_forecasts(before,times,model,motors)
    assert not missing and len(hazards)==1
    actual=after['enemy'];collider=actual['colliders'][0];hazard=hazards[0]
    assert enemy['info_identity']==actual['info_identity']
    assert not enemy['fields']['_dead']and not actual['fields']['_dead']
    assert not before['role']['god']and not before['role']['mounted']
    center=np.array([collider['center'][a]for a in ('x','y')])
    extent=np.array([collider['extents'][a]for a in ('x','y')])
    assert np.all(abs(center-hazard.centers[-1])+extent<=hazard.extents[-1]+hazard.padding)
    assert hazard.geometry=='aabb'and hazard.approximate and hazard.active.all()
    if enemy['fields']['currState']in ('Attack: 3','AttackEnd: 4','End: 5'):
        assert np.linalg.norm(center-hazard.centers[-1])<.0001
    if before['state']['health']!=after['state']['health']:
        assert 'calibration' in case['scope']


@pytest.mark.parametrize('change,reason',[
    ('parent','rock_tiger_head_transform'),
    ('head_rotation','rock_tiger_head_transform'),
    ('root_scale','rock_tiger_nonuniform_or_modified_scale'),
    ('moving_root','rock_tiger_moving_root'),
    ('origin_z','rock_tiger_spatial_head_path'),
    ('capsule_owner','rock_tiger_original_head_capsule'),
    ('capsule_callback','rock_tiger_original_head_capsule'),
    ('capsule_pose','rock_tiger_current_capsule_pose_disagrees'),
    ('speed','rock_tiger_native_parameter_domain'),
    ('clock','rock_tiger_original_fixed_clock'),
    ('target_z','rock_tiger_spatial_aim_reference'),
    ('cancelled_depth','rock_tiger_spatial_aim_reference'),
])
def test_unknown_head_binding_clock_and_spatial_variants_are_rejected(change,reason):
    before=deepcopy(FIXTURE['cases'][0]['before']);e=before['enemies'][0]
    if change=='parent':e['rock_tiger']['head']['direct_parent']=False
    if change=='head_rotation':e['rock_tiger']['head']['identity_rotation']=False
    if change=='root_scale':e['scale']['x']*=2
    if change=='moving_root':e['fields']['_lastPosition']['x']+=1
    if change=='origin_z':e['fields']['originLookAt']['z']=1
    if change=='capsule_owner':e['colliders'][0]['damage_owner']=0
    if change=='capsule_callback':e['colliders'][0]['damage_kind']='attack_module'
    if change=='capsule_pose':e['colliders'][0]['center']['y']+=1
    if change=='speed':e['rock_tiger']['data']['attackSpeed']=0
    if change=='clock':e['fields']['_lastFixedUpdateTime']-=1
    if change=='target_z':before['role']['fields']['_lastRoleObjPos']['z']=1
    if change=='cancelled_depth':
        before['role']['fields']['_lastRoleObjPos']['z']=1
        e['fields']['lookAtOffset']['z']=-1
    result,missing=rock_tiger(e,np.linspace(0.,.5,61),before,PlayerModel(before))
    assert result is None and missing==reason


@pytest.mark.parametrize('limits',[(0.,math.pi),(-6.4,-5.7),(2.,9.),(-.2,.2)])
def test_rotating_capsule_axis_uses_continuous_extrema(limits):
    point=np.array([2.,-.3]);low,high=planar_arc_bounds(point,*limits)
    angles=np.linspace(*limits,10001)
    curve=np.column_stack((point[0]*np.cos(angles)-point[1]*np.sin(angles),
                           point[0]*np.sin(angles)+point[1]*np.cos(angles)))
    assert np.all(curve.min(axis=0)>=low-1e-12)
    assert np.all(curve.max(axis=0)<=high+1e-12)
    assert np.max(abs(curve.min(axis=0)-low))<1e-6
    assert np.max(abs(curve.max(axis=0)-high))<1e-6


def test_aim_is_recomputed_from_the_actual_candidate_actor_trajectory():
    before=deepcopy(FIXTURE['cases'][0]['before']);enemy=before['enemies'][0]
    model=PlayerModel(before);times=np.linspace(0.,1.2,145)
    coast,reason=rock_tiger(enemy,times,before,model)
    assert not reason
    _,motors,valid=model.trajectory(times,((0.,'jump'),))
    assert valid
    jumping,reason=rock_tiger(enemy,times,before,model,motors)
    assert not reason
    a,b=coast[4][enemy['colliders'][0]['id']],jumping[4][enemy['colliders'][0]['id']]
    assert np.max(abs(a[0]-b[0]))>.1
    assert np.max(abs(a[1]-b[1]))>.01


def test_registered_controller_passes_candidate_trajectories_to_aim_forecast(monkeypatch):
    import arena_privileged_policy as policy
    original=policy.hazard_forecasts;supplied=[]
    def traced(observation,times,player,trajectory_states=None,**kwargs):
        supplied.append(trajectory_states is not None)
        return original(observation,times,player,trajectory_states,**kwargs)
    monkeypatch.setattr(policy,'hazard_forecasts',traced)
    before=deepcopy(FIXTURE['cases'][0]['before'])
    policy.InternalController().decide(before)
    assert supplied and not supplied[0]and any(supplied[1:])


def test_retraction_uses_original_attack_speed_even_when_take_back_parameter_differs():
    before=deepcopy(next(c['before']for c in FIXTURE['cases']if c['name']=='retract_to_end'))
    enemy=before['enemies'][0];times=np.linspace(0.,.5,61)
    assert np.linalg.norm([enemy['rock_tiger']['head']['position'][a]for a in ('x','y')])>enemy['rock_tiger']['data']['maxAttackRange']
    original,reason=rock_tiger(enemy,times,before,PlayerModel(before))
    assert not reason
    enemy['rock_tiger']['data']['takeBackSpeed']=1000.
    changed,reason=rock_tiger(enemy,times,before,PlayerModel(before))
    assert not reason
    for old,new in zip(original[4][enemy['colliders'][0]['id']],changed[4][enemy['colliders'][0]['id']]):
        np.testing.assert_array_equal(old,new)


def test_forecast_error_audit_passes_the_delivered_action_to_coupled_enemies(monkeypatch):
    import arena_privileged_runner as runner
    before=deepcopy(FIXTURE['cases'][0]['before']);model=PlayerModel(before)
    assert before['state']['physics'].startswith('runOnLine:')
    after=deepcopy(before);after['state']['time']+=.1
    captured=[]
    def spy(observation,times,player,trajectory_states=None):
        captured.extend(trajectory_states or [])
        return [],[]
    monkeypatch.setattr(runner,'hazard_forecasts',spy)
    runner.forecast_error(before,after,'down')
    assert captured and captured[-1].mode=='rolltolinedown'
