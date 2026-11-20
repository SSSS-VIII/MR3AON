"""Original generated hover balls, linked geometry and pulse transitions."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import connected_electric,suspend_special,suspend_path
from arena_privileged_model import PlayerModel,hazard_forecasts

FIXTURE=json.loads((Path(__file__).parent/'fixtures/arena-privileged-connected-electric.json').read_text())


@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda c:c['name'])
def test_native_reversals_endpoint_geometry_and_pulse_state(case):
    before=case['before'];after=case['after'];enemy=before['enemies'][0]
    dt=after['state']['time']-before['state']['time'];times=np.linspace(0.,dt,round(dt*120)+1)
    assert before['state']['health']==after['state']['health']==5000
    assert before['role']['fields']['_runStopped']and 'StopRun'in case['scope']
    assert not before['role']['mounted']and not before['role']['god']
    hazards,missing=hazard_forecasts(before,times,PlayerModel(before))
    assert not missing and len(hazards)==1
    h=hazards[0];q=after['enemy'];c=q['colliders'][0]
    assert q['info_identity']==enemy['info_identity']and not q['fields']['_dead']
    assert h.active[-1]==(c['active']and c['enabled'])
    if h.active[-1]:
        center=np.array([c['center'][a]for a in ('x','y')]);ext=np.array([c['extents'][a]for a in ('x','y')])
        assert np.all(abs(center-h.centers[-1])+ext<=h.extents[-1]+h.padding)
    if enemy['type']=='EnemySuspendSpecial':
        assert h.geometry=='sphere'
        center=np.array([c['center'][a]for a in ('x','y')])
        assert np.linalg.norm(center-h.centers[-1])<.001
    else:
        assert h.geometry=='aabb'and h.approximate


@pytest.mark.parametrize('change,reason',[
    ('disabled','suspend_special_unverified_or_disabled_controller'),
    ('rotate_parent','suspend_special_unverified_or_disabled_controller'),
    ('owner_recycled','suspend_special_unverified_or_disabled_controller'),
    ('box','suspend_special_original_centered_sphere'),
    ('offset','suspend_special_original_centered_sphere'),
    ('clock','suspend_special_original_fixed_clock'),
    ('range','suspend_special_native_parameter_domain'),
])
def test_generated_spheres_are_not_blindly_aliased_to_hover_family(change,reason):
    before=deepcopy(FIXTURE['cases'][0]['before']);e=before['enemies'][0]
    if change=='disabled':e['fields']['_movementEnable']=False
    if change=='rotate_parent':e['suspend_controller']['type']='EnemyRotateElectricBall'
    if change=='owner_recycled':e['suspend_controller']['alive']=False
    if change=='box':e['colliders'][0]['type']='BoxCollider'
    if change=='offset':e['colliders'][0]['center']['x']+=1
    if change=='clock':e['fields']['_lastFixedUpdateTime']-=1
    if change=='range':e['fields']['_maxY']=e['fields']['_minY']-1
    result,missing=suspend_special(e,np.array([0.,.5]),before,PlayerModel(before))
    assert result is None and missing==reason


@pytest.mark.parametrize('change,reason',[
    ('truncated','electric_connection_original_moving_endpoints'),
    ('endpoint_disabled','electric_connection_original_moving_endpoints'),
    ('endpoint_dead','electric_connection_dead_or_recycled_endpoint'),
    ('endpoint_z','electric_connection_spatial_endpoint'),
    ('endpoint_clock','electric_connection_endpoint_fixed_clock'),
    ('endpoint_nan','electric_connection_endpoint_parameter_domain'),
    ('parent','electric_connection_modified_transform'),
    ('root_moves','electric_connection_moving_parent'),
    ('box_owner','electric_connection_original_link_box'),
    ('ratio','electric_connection_timer_or_length_domain'),
    ('clock','electric_connection_original_fixed_clock'),
    ('enable','electric_connection_native_enable_disagreement'),
])
def test_incomplete_link_binding_and_unknown_control_are_explicit(change,reason):
    before=deepcopy(next(c['before']for c in FIXTURE['cases']if c['name']=='connected_link'))
    e=before['enemies'][0];binding=e['electric_connection']
    if change=='truncated':binding['balls_truncated']=True
    if change=='endpoint_disabled':binding['balls'][0]['fields']['_movementEnable']=False
    if change=='endpoint_dead':binding['balls'][0]['fields']['_dead']=True
    if change=='endpoint_z':binding['balls'][0]['position']['z']+=1
    if change=='endpoint_clock':binding['balls'][0]['fields']['_lastFixedUpdateTime']-=1
    if change=='endpoint_nan':binding['balls'][0]['fields']['_speedY']=float('nan')
    if change=='parent':binding['direct_parent']=False
    if change=='root_moves':e['fields']['_lastPosition']['x']+=1
    if change=='box_owner':e['colliders'][0]['damage_owner']=0
    if change=='ratio':e['fields']['_electricRatio']=0
    if change=='clock':e['fields']['_lastFixedUpdateTime']-=1
    if change=='enable':e['fields']['_electricEnable']=not e['fields']['_electricEnable']
    result,missing=connected_electric(e,np.array([0.,.5]),before,PlayerModel(before))
    assert result is None and missing==reason


def test_fixed_endpoint_samples_keep_both_native_update_orders_at_zero_duration():
    before=FIXTURE['cases'][0]['before'];e=before['enemies'][0]
    result,missing=suspend_path(e,np.array([0.,0.]),before)
    assert not missing
    np.testing.assert_allclose(result[0][0],[e['position'][a]for a in ('x','y')],atol=1e-8)
    np.testing.assert_allclose(result[2][0],[e['fields']['_lastPosition'][a]for a in ('x','y')],atol=1e-4)
    np.testing.assert_allclose(result[3][0],[e['fields']['_secondLastPosition'][a]for a in ('x','y')],atol=1e-4)


@pytest.mark.parametrize('case',json.loads((Path(__file__).parent/'fixtures/arena-privileged-electric-spread.json').read_text())['cases'],ids=lambda c:c['name'])
def test_native_scaled_spreading_link_extends_past_its_endpoints(case):
    before=case['before'];q=case['after']['enemy'];enemy=before['enemies'][0]
    assert enemy['scale']['x']==enemy['scale']['y']==1.5
    assert case['actual_overhang_x_m']>1.
    assert not before['role']['god']and not before['role']['mounted']
    dt=case['after']['state']['time']-before['state']['time'];times=np.linspace(0.,dt,round(dt*120)+1)
    original=deepcopy(before);hazards,missing=hazard_forecasts(before,times,PlayerModel(before))
    assert before==original and not missing and len(hazards)==1
    c=next(c for c in q['colliders']if c['id']==hazards[0].id)
    center=np.array([c['center'][a]for a in ('x','y')]);ext=np.array([c['extents'][a]for a in ('x','y')])
    assert np.all(abs(center-hazards[0].centers[-1])+ext<=hazards[0].extents[-1])
