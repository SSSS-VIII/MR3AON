"""Original cliff departure and spring contact at a different fixed/render phase."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-spring-physical-phase.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_native_cliff_and_spring_update_do_not_depend_on_requested_observation_grid(case):
    o,q=case['before'],case['after'];model=PlayerModel(o)
    dt=q['state']['time']-o['state']['time'];target=q['role']['colliders'][0]
    endpoints=[]
    for grid in (np.array([0.,dt]),np.linspace(0,dt,31),np.linspace(0,dt,61)):
        body,motors,valid=model.trajectory(grid)
        assert valid and not model.unsupported
        assert np.linalg.norm(body[-1,:2]-[target['center'][a]for a in ('x','y')])<.0002
        assert motors[-1].vy==pytest.approx(q['role']['velocity']['y'],abs=.0001)
        endpoints.append(body[-1])
    assert np.allclose(endpoints,endpoints[0],atol=1e-8,rtol=0)


def test_actual_physical_pickup_is_already_inside_while_the_render_pose_still_misses():
    model=PlayerModel(DATA['cases'][-1]['before'])
    low=min(model.spring_launches,key=lambda item:item['position']['y'])
    physical=replace(model.initial,x=model.initial.physical_x,y=model.initial.physical_y)
    assert model.spring_distance(model.initial,low)>0
    assert model.spring_distance(physical,low)<0
    # IsCanPop also accepts a new spring during PopFall. The consumed spring
    # is identified by its native normal visual, not by current role mode.
    motor=replace(model.initial,mode='popfall',spring_ready=True)
    used=set()
    assert model.spring_launch(motor,physical,used,model.tick)
    assert motor.mode=='popup'and used=={low['id']}
