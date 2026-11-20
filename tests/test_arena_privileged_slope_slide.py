"""Native slope slide uses tangent speed and both recovery offset updates."""
import json
import math
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-slope-slide.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_native_up_down_slide_entry_motion_and_recovery_capsule(case):
    o,q=case['before'],case['after'];dt=q['state']['time']-o['state']['time']
    model=PlayerModel(o);times=np.linspace(0,dt,round(dt*120)+1)
    bodies,motors,valid=model.trajectory(times,case['operations']);assert valid
    c=q['role']['colliders'][0];actual=np.array([c['center'][a]for a in ('x','y')]);body=bodies[-1]
    # Eight retained native pairs; max error in the broader 320-pair audit
    # is 1.245 mm, including large float32 absolute-clock interpolation.
    assert np.linalg.norm(body[:2]-actual)<.0015
    assert motors[-1].mode==q['state']['physics'].split(':')[0].lower()
    axis=('x','y','z')[c['direction']]
    radius=c['radius']*max(abs(c['scale'][a])for a in ('x','y','z')if a!=axis)
    half=max(0.,c['height']*abs(c['scale'][axis])/2-radius)
    angle=math.radians(c['rotation_z']);direction=np.array([-math.sin(angle),math.cos(angle)])
    for endpoint in (actual-half*direction,actual+half*direction):
        delta=endpoint-body[:2]
        distance=math.hypot(delta[0],max(0.,abs(delta[1])-body[3]))
        assert distance+radius<=body[2]+.0015
    assert not o['role']['god']and not o['role']['mounted']
