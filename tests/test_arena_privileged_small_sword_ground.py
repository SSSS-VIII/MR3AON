"""Original sword pivot follows ground cache through slopes and air inputs."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_families import small_sword

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-small-sword-ground.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_native_slope_wait_charge_flight_and_ui_jump_down_pairs(case):
    o=case['before'];q=case['after'];original=deepcopy(o)
    dt=q['state']['time']-o['state']['time'];times=np.linspace(0,dt,round(dt*120)+1)
    model=PlayerModel(o);_,motors,valid=model.trajectory(times,case['operations'])
    assert valid
    hs,missing=hazard_forecasts(o,times,model,motors)
    assert not missing and len(hs)==1 and o==original
    h=hs[0];c=next(v for v in q['enemy']['colliders']if v['id']==h.id)
    actual=np.array([c['center'][a]for a in ('x','y')]);extent=np.array([c['extents'][a]for a in ('x','y')])
    assert np.all(abs(actual-h.centers[-1])+extent<=h.extents[-1]+h.padding)
    assert h.geometry=='aabb'and h.quads is None and h.approximate and h.active.all()
    assert 'cached terrain/platform ground interval'in h.source
    assert o['role']['ground_reference_y']!=pytest.approx(q['enemy']['fields']['_pivotPos']['y'])
    assert not o['role']['god']and not o['role']['mounted']


def test_wait_without_follow_cancels_pivot_movement_until_original_charge_starts():
    c=DATA['cases'][0];e=c['before']['enemies'][0];q=c['after']['enemy']
    assert e['fields']['_stayRefNinja']is False
    assert e['fields']['_enemyState']==q['fields']['_enemyState']=='Wait: 1'
    assert q['fields']['_pivotPos']['y']>e['fields']['_pivotPos']['y']+.1
    assert abs(q['position']['y']-e['position']['y'])<.0001


@pytest.mark.parametrize('change,reason',[
    ('cache','small_sword_player_speed_transition'),
    ('excluded','small_sword_excluded_platform_transition'),
    ('nonfinite','small_sword_native_parameter_domain'),
    ('spatial','small_sword_spatial_reference'),
    ('terrain','small_sword_resolved_ground_reference_missing'),
    ('gap','small_sword_ground_reference_gap'),
    ('direction','small_sword_reference_run_direction'),
])
def test_unknown_cache_terrain_or_original_reference_still_stops_prediction(change,reason):
    o=deepcopy(DATA['cases'][0]['before']);e=o['enemies'][0]
    if change=='cache':o['role'].pop('ground_reference_y')
    if change=='excluded':o['role']['excluded_air_ground']['present']=True
    if change=='nonfinite':e['fields']['_velocity']['y']=float('nan')
    if change=='spatial':e['fields']['_localPos']['z']=1.
    if change=='terrain':o['terrain']=[]
    if change=='gap':
        for b in o['terrain']:b['start']['x']+=1000;b['finish']['x']+=1000
    if change=='direction':o['camera']['direction']=-1
    p,missing=small_sword(e,np.linspace(0.,.5,61),o,PlayerModel(o),None)
    assert p is None and missing==reason
