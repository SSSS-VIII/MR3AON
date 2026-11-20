"""Native distance activation and flex settling, with original role clocks."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts,spider_positions,clearance
from arena_privileged_families import spider_entry

FIXTURE=json.loads((Path(__file__).parent/'fixtures/arena-privileged-spider-entry.json').read_text())
FLEX=next(c for c in FIXTURE['cases']if c['before']['enemies'][0]['fields']['_enemyState']=='flex: 2')


@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda c:c['name'])
def test_native_entry_and_flex_collision_envelopes_contain_later_original_shape(case):
    b,a=case['before'],case['after'];dt=a['state']['time']-b['state']['time']
    times=np.linspace(0,dt,round(dt*120)+1)
    hs,missing=hazard_forecasts(b,times,PlayerModel(b))
    assert not missing and len(hs)==1
    h=hs[0];c=a['enemy']['colliders'][0]
    actual=np.array([c['center'][x]for x in ('x','y')]);ext=np.array([c['extents'][x]for x in ('x','y')])
    assert np.all(abs(actual-h.centers[-1])+ext<=h.extents[-1]+h.padding)
    assert b['state']['health']==a['state']['health']>0
    assert not b['role']['god'] and not a['role']['god']
    assert not b['role']['mounted'] and not a['role']['mounted']
    if b['enemies'][0]['fields']['_enemyState']=='none: 9':
        # An uncertain drop is a vertical union, not a sphere whose radius
        # ignores the extra Y extent. Its lower endpoint must remain lethal.
        assert h.geometry=='aabb' and h.approximate
        body=np.tile([h.centers[-1,0],h.centers[-1,1]-h.extents[-1,1],.1,0.],(len(times),1))
        assert clearance(body,h)[-1]<0


def test_flex_clamps_a_crossed_target_in_the_same_native_tick():
    case=FLEX;b=case['before'];a=case['after'];e=b['enemies'][0]
    dt=a['state']['time']-b['state']['time']
    predicted=spider_positions(e,np.array([0.,dt]),stamp=b['state']['time'],tick=b['state']['fixedDeltaTime'])
    assert abs(predicted[-1]-a['enemy']['position']['y'])<.0005


def test_stay_honors_original_up_speed_instead_of_freezing_the_root():
    b=FLEX['before'];e=deepcopy(b['enemies'][0])
    e['fields']['_enemyState']='stay: 1';e['custom']['_upSpeed']=2.5
    e['fields']['_lastPosition']['y']=e['position']['y']
    e['fields']['_secondLastPosition']['y']=e['position']['y']-2.5*b['state']['fixedDeltaTime']
    ys=spider_positions(e,np.array([0.,.1]),stamp=b['state']['time'],tick=b['state']['fixedDeltaTime'])
    assert ys[-1]-ys[0]==pytest.approx(.25,abs=1e-5)


@pytest.mark.parametrize('change,reason',[
    ('direction','spider_original_run_direction'),
    ('render','spider_unverified_entry_render'),
    ('shape','spider_unverified_entry_shape'),
    ('inactive','spider_unverified_entry_shape'),
    ('clock','spider_original_reference_clock'),
    ('reference','spider_original_role_reference'),
])
def test_unproved_entry_variants_are_not_silently_stationary(change,reason):
    b=deepcopy(FIXTURE['cases'][0]['before']);e=b['enemies'][0]
    if change=='direction':b['camera']['direction']=-1
    if change=='render':e['fields']['_renderType']=1
    if change=='shape':e['colliders'][0]['damage_owner']+=1
    if change=='inactive':e['colliders'][0]['active']=False
    if change=='clock':e['fields']['_lastFixedUpdateTime']-=.02
    if change=='reference':b['role']['fields']['_lastRoleObjPos']['x']+=1
    prediction,missing=spider_entry(e,np.linspace(0,.2,25),b,PlayerModel(b))
    assert prediction is None and missing==reason


def test_slope_acceleration_and_candidate_jump_supply_actual_physical_reference_positions():
    b=next(c['before']for c in FIXTURE['cases']if c['name']=='slope_distance_trigger')
    p=PlayerModel(b);times=np.linspace(0,1.8,217)
    for operations in ((),((.1,'jump'),)):
        _,motors,valid=p.trajectory(times,operations)
        assert valid and any(abs(m.vx-b['state']['speed'])>.001 for m in motors)
        prediction,missing=spider_entry(b['enemies'][0],times,b,p,motors)
        assert missing is None and prediction is not None


def test_bite_feedback_geometry_is_explicitly_rejected_until_authored_curves_are_modelled():
    b=deepcopy(FIXTURE['cases'][0]['before']);b['enemies'][0]['fields']['_enemyState']='bite: 8'
    hs,missing=hazard_forecasts(b,np.linspace(0,.2,25),PlayerModel(b))
    assert not hs and missing[0]['reason']=='spider_bite_feedback_geometry'
