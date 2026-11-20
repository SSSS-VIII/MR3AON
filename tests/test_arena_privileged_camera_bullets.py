"""Actual generated projectiles keep their original camera-relative X."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_families import camera_relative_bullet
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-camera-bullets.json').read_text())

@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_native_acceleration_camera_reference_and_original_damage_shape(case):
    o=case['before'];q=case['after']['enemy'];dt=case['after']['state']['time']-o['state']['time']
    times=np.linspace(0.,dt,round(dt*120)+1);original=deepcopy(o)
    hs,missing=hazard_forecasts(o,times,PlayerModel(o))
    assert not missing and len(hs)==1 and o==original
    assert not o['role']['mounted']and not o['role']['god']
    h=hs[0];c=next(c for c in q['colliders']if c['id']==h.id)
    actual=np.array([c['center'][a]for a in ('x','y')]);extent=np.array([c['extents'][a]for a in ('x','y')])
    assert np.all(abs(actual-h.centers[-1])+extent<=h.extents[-1])
    assert h.active[-1]and h.approximate and h.geometry=='aabb'
    if q['type']=='EnemyBullutFireRobot':
        # It can move right in world X while its own local direction points
        # left. Neither raw local speed nor root velocity is the full motion.
        e=o['enemies'][0];assert e['fields']['_moveDir']['x']<0
        assert q['fields']['_bullutSpeed']>e['fields']['_bullutSpeed']

@pytest.mark.parametrize('change,reason',[
 ('parent','fire_bullet_unverified_parent_or_bullet_type'),
 ('bullet_type','fire_bullet_unverified_parent_or_bullet_type'),
 ('animation','fire_bullet_unverified_damage_transform_chain'),
 ('rigidbody','fire_bullet_unverified_dynamic_rigidbody'),
 ('incomplete_native_components','fire_bullet_unverified_damage_transform_chain'),
 ('callback','fire_bullet_original_damage_box'),
 ('clock','fire_bullet_original_reference_clock'),
 ('spatial','fire_bullet_nonplanar_or_nonfinite_parameters'),
 ('nonfinite','fire_bullet_nonplanar_or_nonfinite_parameters'),
 ('reference_override','fire_bullet_unknown_reference_override'),
])
def test_unknown_spatial_control_or_physics_cannot_become_constant_speed_boxes(change,reason):
    o=deepcopy(DATA['cases'][0]['before']);e=o['enemies'][0];b=e['bullet_geometry'];f=e['fields']
    if change=='parent':b['parent_axes_identity']=False
    if change=='bullet_type':f['_bullutType']=1
    if change=='animation':b['chains'][0]['nodes'][0]['scripts'].append('UnityEngine.Animator')
    if change=='rigidbody':
        next(n for n in b['chains'][0]['nodes']if 'rigidbody'in n)['rigidbody']['kinematic']=False
    if change=='incomplete_native_components':b['chains'][0].pop('includes_native_components')
    if change=='callback':e['colliders'][0]['damage_owner']=0
    if change=='clock':f['_lastFixedUpdateTime']-=1
    if change=='spatial':f['_moveDir']['z']=1
    if change=='nonfinite':f['_speedAcc']=float('nan')
    if change=='reference_override':f['_pivotPos']['x']+=100;f['_localPos']['x']-=100
    result,missing=camera_relative_bullet(e,np.array([0.,.5]),o,PlayerModel(o))
    assert result is None and missing==reason

@pytest.mark.parametrize('change,reason',[
 ('position_root','laser_growth_unverified_translation_binding'),
 ('position_rect','laser_growth_unverified_translation_binding'),
 ('position_easing','laser_growth_unverified_translation_easing'),
 ('position_missing','laser_growth_original_translation_missing'),
 ('scale_curve_truncated','laser_growth_original_posed_box'),
 ('scale_easing','laser_growth_unverified_easing'),
])
def test_laser_translation_and_scale_must_both_be_bound_to_original_shape(change,reason):
    o=deepcopy(DATA['cases'][2]['before']);e=o['enemies'][0];growth=e['laser_growth']
    if change=='position_root':growth['positions'][0]['root']+=1
    if change=='position_rect':growth['positions'][0]['fields']['isRect']=True
    if change=='position_easing':growth['positions'][0]['fields']['method']='EaseIn: 1'
    if change=='position_missing':growth['positions']=[]
    if change=='scale_curve_truncated':growth['scales'][0]['curve_truncated']=True
    if change=='scale_easing':growth['scales'][0]['fields']['method']='EaseIn: 1'
    result,missing=camera_relative_bullet(e,np.array([0.,.5]),o,PlayerModel(o))
    assert result is None and missing==reason


def test_native_laser_can_grow_beyond_authored_final_scale():
    case=DATA['cases'][2];e=case['before']['enemies'][0];q=case['after']['enemy']
    assert e['colliders'][0]['scale']['x']<.3
    assert q['colliders'][0]['scale']['x']>1.6
    assert e['laser_growth']['scales'][0]['fields']['to']['x']==1.5
