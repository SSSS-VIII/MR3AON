"""Original small-sword wait/charge/flight, rather than one linear projectile."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_families import small_sword

FIXTURE=json.loads((Path(__file__).parent/'fixtures/arena-privileged-small-sword.json').read_text())


@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda c:c['name'])
def test_original_wait_charge_and_flight_pairs(case):
    before=case['before'];after=case['after'];dt=after['state']['time']-before['state']['time']
    model=PlayerModel(before);assert not model.unsupported
    times=np.linspace(0,dt,round(dt*120)+1)
    hazards,missing=hazard_forecasts(before,times,model)
    assert not missing and len(hazards)==1
    actual=after['enemy']['colliders'][0];h=hazards[0]
    center=np.array([actual['center'][a]for a in ('x','y')])
    extents=np.array([actual['extents'][a]for a in ('x','y')])
    assert np.linalg.norm(center-h.centers[-1])<.001
    assert np.all(abs(center-h.centers[-1])+extents<=h.extents[-1]+h.padding)
    assert h.active.all() and h.approximate
    assert before['state']['health']==after['state']['health']==5000
    # The source's local velocity is not its world velocity: the physical
    # player X remains part of the pivot even after the projectile launches.
    enemy=before['enemies'][0]
    guessed=enemy['colliders'][0]['center']['x']+enemy['fields']['_velocity']['x']*dt
    assert abs(guessed-center[0])>1.


@pytest.mark.parametrize('change,reason',[
    ('hidden','small_sword_phase:hide'),
    ('breath','small_sword_unverified_breath_transform'),
    ('owner','small_sword_original_box_binding'),
    ('clock','small_sword_reference_clock'),
    ('speed','small_sword_player_speed_transition'),
    ('slope','small_sword_nonconstant_ground_reference'),
    ('pivot','small_sword_reference_position'),
    ('spatial','small_sword_spatial_reference'),
])
def test_unproved_appearance_reference_and_shape_states_are_rejected(change,reason):
    before=deepcopy(FIXTURE['cases'][0]['before']);enemy=before['enemies'][0]
    if change=='hidden':enemy['fields']['_enemyState']='Hide: 0'
    if change=='breath':enemy['sword']['breath_affects_damage']=True
    if change=='owner':enemy['colliders'][0]['damage_owner']+=1
    if change=='clock':enemy['fields']['_lastFixedUpdateTime']-=.02
    if change=='speed':before['role']['velocity']['x']+=2
    if change=='slope':
        for row in before['supports']:row['finish']['y']+=1
    if change=='pivot':enemy['fields']['_pivotPos']['x']+=1
    if change=='spatial':enemy['fields']['_velocity']['z']=1
    model=PlayerModel(before)
    prediction,missing=small_sword(enemy,np.linspace(0,.5,61),before,model,None)
    assert prediction is None and missing==reason


def test_future_player_speed_changes_cannot_reuse_constant_reference_forecast():
    before=FIXTURE['cases'][0]['before'];model=PlayerModel(before);times=np.linspace(0,.5,61)
    _,motors,_=model.trajectory(times);motors[-1].vx+=1
    result,reason=small_sword(before['enemies'][0],times,before,model,motors)
    assert result is None and reason=='small_sword_player_speed_transition'
