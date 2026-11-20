"""Original downhill exit: native slope ratio persists after returning to flat."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel

CASES=json.loads((Path(__file__).parent/'fixtures/arena-privileged-slope-settle.json').read_text())


@pytest.mark.parametrize('case',CASES,ids=lambda c:str(c['source_indices']))
def test_actual_body_contact_and_stale_slope_ratio_at_flat_ground_exit(case):
    before,after=case['before'],case['after'];dt=case['seconds']
    model=PlayerModel(before)
    assert before['role']['slope_state']==0
    assert before['role']['fields']['_slopeSpeedRatio']>1.3
    assert model.initial.offset_render>2.7
    surface=model.surface(model.initial,0.)
    assert surface.id==before['support_id'] and surface.slope==0
    # Parent root is still before the segment. The collider parent has already
    # entered it, exactly as the original GroundCollider reference says.
    assert not surface.contains(model.initial.x)
    body,motors,valid=model.trajectory(np.linspace(0,dt,round(dt*120)+1))
    target=after['role']['colliders'][0]['center']
    assert valid and motors[-1].mode=='runonground'
    assert np.linalg.norm(body[-1,:2]-[target['x'],target['y']])<.001
