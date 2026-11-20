"""Native piranha phases, callback activation and original root-box envelope."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_families import piranha,piranha_steps

FIXTURE=json.loads((Path(__file__).parent/'fixtures/arena-privileged-piranha.json').read_text())


@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda c:c['name'])
def test_original_phase_scale_and_hurt_shape_are_enclosed(case):
    before=case['before'];after=case['after'];dt=after['state']['time']-before['state']['time']
    times=np.linspace(0,dt,round(dt*120)+1);model=PlayerModel(before)
    hazards,missing=hazard_forecasts(before,times,model)
    assert not missing and len(hazards)==1
    e=before['enemies'][0];q=after['enemy'];c=q['colliders'][0];h=hazards[0]
    assert e['info_identity']==q['info_identity'] and not q['fields']['_dead']
    if c['enabled']:
        assert h.active[-1]
        center=np.array([c['center'][a]for a in ('x','y')])
        extent=np.array([c['extents'][a]for a in ('x','y')])
        assert np.all(abs(center-h.centers[-1])+extent<=h.extents[-1]+h.padding)
    # Enclose the actual original root box in 3D before projecting into XY;
    # a rotating box's current 2D extents cannot bound its future orientation.
    original=e['colliders'][0]
    radius=(np.linalg.norm([original['size'][a]for a in ('x','y','z')])/2
            +np.linalg.norm([original['local_center'][a]for a in ('x','y','z')]))
    assert original['rotation_envelope']['depth']==0
    assert radius==pytest.approx(original['rotation_envelope']['root_radius'],abs=1e-6)
    result,reason=piranha(e,times,before,model)
    assert reason is None
    errors=[]
    for activation in result[5]['activation_ticks']:
        positions,states,_=piranha_steps(e,times,before,activation)
        errors.append(np.linalg.norm(positions[-1]-[q['position'][a]for a in ('x','y')]))
        if errors[-1]<.0001:
            assert states[-1,1]==pytest.approx(q['scale']['x'],abs=1e-6)
            assert bool(states[-1,0])==c['enabled']
            assert int(states[-1,2])==int(q['fields']['_enemyState'].rsplit(':',1)[1])
    assert min(errors)<.0001
    assert h.approximate and h.geometry=='sphere'
    if before['state']['health']!=after['state']['health']:
        assert case.get('scope') # An enemy calibration pair, not a no-injury route.


@pytest.mark.parametrize('change,reason',[
    ('parent','piranha_render_or_parent_space'),
    ('variant','piranha_render_or_parent_space'),
    ('callback','piranha_original_root_box'),
    ('child','piranha_original_root_box'),
    ('scale','piranha_native_scale_domain'),
    ('nan','piranha_nonfinite_native_parameters'),
    ('clock','piranha_original_fixed_clock'),
    ('reverse','piranha_original_run_direction'),
    ('ground','piranha_ground_reference_crossing'),
])
def test_unproved_reference_and_geometry_variants_are_explicit(change,reason):
    before=deepcopy(FIXTURE['cases'][0]['before']);e=before['enemies'][0]
    if change=='parent':e['local_movement_parent_identity']=False
    if change=='variant':e['custom']['_render']=1
    if change=='callback':e['colliders'][0]['damage_kind']='attack_module'
    if change=='child':e['colliders'][0]['rotation_envelope']['depth']=1
    if change=='scale':e['scale']['z']*=2
    if change=='nan':e['fields']['_gravity']=float('nan')
    if change=='clock':e['fields']['_lastFixedUpdateTime']-=1
    if change=='reverse':before['camera']['direction']=-1
    if change=='ground':e['native_support']['finish']['y']+=1
    result,missing=piranha(e,np.linspace(0,.5,61),before,PlayerModel(before))
    assert result is None and missing==reason


def test_zero_wait_original_entry_skips_the_waiting_state():
    before=next(c['before']for c in FIXTURE['cases']if c['name']=='none_to_jump')
    enemy=before['enemies'][0];assert enemy['fields']['_stayTime']==0
    tick=before['state']['fixedDeltaTime'];age=before['state']['time']-enemy['fields']['_lastFixedUpdateTime']
    times=np.array([0,tick-age+.000001])
    _,states,_=piranha_steps(enemy,times,before,activation_tick=1)
    assert states[-1,2]==2 # PreJump, not Wait.


def test_conditional_enemy_calibration_does_not_allow_unknown_item_contacts():
    from arena_privileged_policy import InternalController
    before=next(c['before']for c in FIXTURE['cases']if c['name']=='none_to_jump')
    assert 'item:ItemShell' in PlayerModel(before).unsupported
    proposal=InternalController().decide(before)
    assert proposal.reason=='unsupported_native_mechanism' and proposal.action=='none'
    assert 'item:ItemShell' in proposal.evidence['unsupported_role']
