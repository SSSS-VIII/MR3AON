"""Original horizontal no-jump spring flight, after the pickup has occurred."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-popfall.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_native_popfall_keeps_horizontal_speed_and_lands_on_integrated_frame(case):
    o,q=case['before'],case['after'];original=deepcopy(o)
    model=PlayerModel(o);assert not model.unsupported
    dt=q['state']['time']-o['state']['time'];times=np.linspace(0,dt,max(2,round(dt*120)+1))
    body,motors,valid=model.trajectory(times);b=q['role']['colliders'][0]
    assert valid and o==original
    assert np.linalg.norm(body[-1,:2]-[b['center'][a]for a in ('x','y')])<.002
    assert motors[-1].mode==q['state']['physics'].split(':',1)[0].lower()
    assert motors[-1].vx==pytest.approx(q['role']['velocity']['x'],abs=.0001)
    assert motors[-1].vy==pytest.approx(q['role']['velocity']['y'],abs=.0001)
    assert not o['role']['god']and not q['role']['god']


def test_original_gravity_switch_uses_down_gravity_three_after_first_launch_tick():
    o=deepcopy(DATA['cases'][0]['before'])
    assert o['role']['gravity']==o['role']['data']['_downGravity1']==-9.
    o['role']['data']['_downGravity2']=-50.
    model=PlayerModel(o);ts=np.array([0.,model.tick]);_,motors,valid=model.trajectory(ts)
    assert valid
    expected=np.float32(np.float32(o['role']['velocity']['y'])+np.float32(np.float32(
        np.float32(o['role']['data']['_downGravity3'])*np.float32(model.tick))*np.float32(3.5)))
    assert motors[-1].vy==float(expected)


@pytest.mark.parametrize('change',['continue','jump','direction','platform','nonfinite'])
def test_other_pop_rules_are_rejected_instead_of_guessing_their_controls(change):
    o=deepcopy(DATA['cases'][0]['before']);f=o['role']['fields']
    if change=='continue':f['_continuePop']=True
    if change=='jump':f['_popCanJump']=True
    if change=='direction':f['_popDirection']['y']=.1
    if change=='platform':o['platforms']=[dict(id=1,is_current=False,info=dict(_leftX=0.,_rightX=1.,_topY=0.))]
    if change=='nonfinite':o['role']['data']['_downGravity3']=float('nan')
    model=PlayerModel(o)
    assert 'native_popfall_variant'in model.unsupported


def test_horizontal_no_jump_launch_does_not_invent_an_air_flip_or_jump():
    model=PlayerModel(DATA['cases'][0]['before'])
    for action in ('jump','down'):
        _,_,valid=model.trajectory(np.array([0.,.1]),((0.,action),))
        assert not valid


def test_post_spring_camera_launch_is_not_claimed_before_original_pair_validation():
    o=deepcopy(DATA['cases'][0]['before'])
    native=json.loads((Path(__file__).parent/'fixtures/arena-privileged-tracking-bamboo.json').read_text())
    enemy=next(e for e in native['cases'][0]['before']['enemies']if e['type']=='EnemyFlyBamboo')
    o['enemies']=[enemy];hs,missing=hazard_forecasts(o,np.linspace(0,.2,25),PlayerModel(o))
    assert not any(h.enemy==enemy['id']for h in hs)
    assert dict(id=enemy['id'],type='EnemyFlyBamboo',reason='spring_pop_camera_transition_not_validated')in missing
