"""Source rigid assembly, disabled child clocks and native paired geometry."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_families import rotating_electric,rotating_ball
FIXTURE=json.loads((Path(__file__).parent/'fixtures/arena-privileged-rotating-electric.json').read_text())

@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda c:c['name'])
def test_native_rigid_link_and_disabled_child_follow_original_parent(case):
    o=case['before'];e=o['enemies'][0];q=case['after']['enemy'];dt=case['after']['state']['time']-o['state']['time']
    assert not o['role']['mounted']and not o['role']['god']
    original=deepcopy(o);times=np.linspace(0.,dt,round(dt*120)+1)
    hs,missing=hazard_forecasts(o,times,PlayerModel(o))
    assert not missing and len(hs)==1 and o==original
    h=hs[0];c=next(c for c in q['colliders']if c['id']==h.id)
    assert h.active[-1]==(c['active']and c['enabled'])
    center=np.array([c['center'][a]for a in ('x','y')]);extent=np.array([c['extents'][a]for a in ('x','y')])
    assert np.all(abs(center-h.centers[-1])+extent<=h.extents[-1]+h.padding)
    if e['type']=='EnemySuspendSpecial':
        assert e['fields']['_movementEnable']is False and e['fields']['_lastFixedUpdateTime']==0
        assert np.linalg.norm(center-h.centers[-1])<.001
        assert h.geometry=='sphere'
    else:assert h.geometry=='obb'

@pytest.mark.parametrize('change,reason',[
 ('parent','rotating_electric_unverified_rigid_transform'),
 ('tilt','rotating_electric_unverified_rigid_transform'),
 ('scale','rotating_electric_unverified_rigid_transform'),
 ('child_enabled','rotating_electric_unverified_disabled_endpoints'),
 ('child_reparented','rotating_electric_unverified_disabled_endpoints'),
 ('clock','rotating_electric_original_parent_clock'),
 ('parameter','rotating_electric_native_parameter_domain'),
 ('box_owner','rotating_electric_original_link_box'),
 ('pulse','rotating_electric_native_pulse_domain'),
 ('enabled','rotating_electric_native_enable_disagreement'),
])
def test_unknown_assembly_or_native_clock_is_not_silently_aliased(change,reason):
    o=deepcopy(FIXTURE['cases'][0]['before']);e=o['enemies'][0];b=e['rigid_electric']
    if change=='parent':b['parent_axes_identity']=False
    if change=='tilt':b['local_rotation']['x']=20
    if change=='scale':e['scale']['y']*=2
    if change=='child_enabled':b['balls'][0]['movement_enabled']=True
    if change=='child_reparented':b['balls'][0]['direct_parent']=False
    if change=='clock':e['fields']['_lastFixedUpdateTime']-=1
    if change=='parameter':e['fields']['_rotateSpeed']=float('nan')
    if change=='box_owner':e['colliders'][0]['damage_owner']=0
    if change=='pulse':e['fields']['_durationTimer']=float('nan')
    if change=='enabled':e['fields']['_electricEnable']=not e['fields']['_electricEnable']
    result,missing=rotating_electric(e,np.array([0.,.5]),o,PlayerModel(o))
    assert result is None and missing==reason


def test_disabled_child_uses_live_owner_binding_instead_of_its_stale_hover_clock():
    o=deepcopy(FIXTURE['cases'][1]['before']);e=o['enemies'][0]
    for b in e['suspend_controller']['rigid_electric']['balls']:
        if b['id']==e['id']:b['id']=12345
    result,missing=rotating_ball(e,np.array([0.,.5]),o,PlayerModel(o))
    assert result is None and missing=='rotating_ball_original_live_owner'


def test_original_one_tick_off_interval_is_not_rounded_into_permanent_beam():
    o=deepcopy(FIXTURE['cases'][0]['before']);e=o['enemies'][0];f=e['fields']
    f['_durationTimer']=f['_durationTime'];f['_interalTime']=0
    o['state']['time']=f['_lastFixedUpdateTime']
    times=np.array([0.,.02,.04]);r,missing=rotating_electric(e,times,o,PlayerModel(o))
    assert not missing and list(r[3])==[True,False,True]


def test_native_pending_stop_does_not_extrapolate_preceding_actor_speed():
    o=FIXTURE['pending_speed_stop']['before'];e=next(e for e in o['enemies']if e['type']=='EnemyRotateElectricBall')
    assert o['role']['fields']['_runStopped']and o['state']['speed']==20
    assert FIXTURE['pending_speed_stop']['after']['speed']==0
    result,reason=rotating_electric(e,np.array([0.,.1]),o,PlayerModel(o))
    assert result is None and reason=='rotating_electric_pending_actor_speed_stop'


def test_zero_speed_after_release_is_not_assumed_to_stay_zero():
    o=deepcopy(FIXTURE['cases'][0]['before']);o['state']['speed']=0
    o['role']['fields']['_runStopped']=False
    result,reason=rotating_electric(o['enemies'][0],np.array([0.,.1]),o,PlayerModel(o))
    assert result is None and reason=='rotating_electric_unverified_zero_or_resuming_actor_speed'
