"""Paired original fixed-clock actions and finite slope/support transitions."""
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,phase

CASES=json.loads((Path(__file__).parent/'fixtures/arena-privileged-native-motor-v2.json').read_text())


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['name'])
def test_original_physics_and_UI_actions_across_slopes_and_rope(case):
    before=case['before'];model=PlayerModel(before)
    for target in case['targets']:
        elapsed=target['state']['time']-before['state']['time']
        operations=tuple((o['time'],o['action'])for o in case['operations']if o['time']<elapsed-1e-8)
        # Sparse output must still preserve every original fixed update.
        body,states,valid=model.trajectory(np.array([0.,elapsed]),operations)
        motor=states[-1];actual=target['body'];eps=case['tolerance_m']
        assert valid
        assert motor.mode==phase(target['state']['physics'])
        assert target['state']['health']==before['state']['health']==5000
        assert np.linalg.norm(np.array([motor.x,motor.y])-[target['state']['position'][a]for a in ('x','y')])<eps
        assert abs(motor.vx-target['velocity']['x'])<.0001
        assert abs(motor.vy-target['velocity']['y'])<.0001
        # Compare the complete original capsule to the planning capsule. Roll
        # offsets rotate; their center is enclosed instead of fixed at root.
        scale=actual['scale'];direction=('x','y','z')[actual['direction']]
        radius=actual['radius']*max(abs(scale[a])for a in ('x','y','z')if a!=direction)
        half=max(0.,actual['height']*abs(scale[direction])/2-radius)
        assert direction=='y'
        angle=math.radians(actual['rotation_z']);axis=np.array([-math.sin(angle),math.cos(angle)])
        center=np.array([actual['center'][a]for a in ('x','y')])
        for sign in (-1,1):
            point=center+sign*half*axis
            nearest=np.array([body[-1,0],np.clip(point[1],body[-1,1]-body[-1,3],body[-1,1]+body[-1,3])])
            assert np.linalg.norm(point-nearest)+radius<=body[-1,2]+eps


def test_resampling_does_not_move_the_original_jump_apex_or_landing():
    case=next(c for c in CASES if c['name']=='uphill_UI_jump_land')
    model=PlayerModel(case['before']);dt=case['targets'][-1]['state']['time']-case['before']['state']['time']
    coarse,cs,cv=model.trajectory(np.array([0.,dt]),((0.,'jump'),))
    dense,ds,dv=model.trajectory(np.linspace(0.,dt,241),((0.,'jump'),))
    assert cv and dv and cs[-1].mode==ds[-1].mode=='runonground'
    assert np.linalg.norm(coarse[-1]-dense[-1])<1e-8
