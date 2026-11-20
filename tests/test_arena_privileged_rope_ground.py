"""Native failure: hanging below a rope gets stuck before same-height ground."""
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel
from arena_privileged_policy import InternalController

CASE=json.loads((Path(__file__).parent/'fixtures/arena-privileged-rope-ground.json').read_text())


def test_original_rope_to_ground_dead_end_requires_flip_before_native_clamp():
    obs=CASE['before'];after=CASE['after_coast'];model=PlayerModel(obs)
    assert obs['state']['physics'].startswith('runOnLineDown:')
    assert after['state']['health']==0 and after['state']['physics'].startswith('dieDownLine:')
    times=np.linspace(0,1.8,217);_,states,_=model.trajectory(times)
    contact=np.flatnonzero(model.terrain_clearances(states)<=0)[0]
    ground=next(r for r in obs['terrain'] if r['kind'].startswith('ground:') and
                r['start']['x']>model.initial.x)
    assert states[contact].x<ground['start']['x']
    assert abs(after['state']['position']['x']-(ground['start']['x']-model.data['_climbDistance']))<.001
    proposal=InternalController().decide(obs)
    assert proposal.reason=='approach_center_of_native_safe_window'
    assert proposal.evidence['window_choice']['action']=='jump'
    for delta in (-.04,.04):
        _,motors,valid=model.trajectory(times,((proposal.delay+delta,'jump'),))
        assert valid and model.terrain_clearances(motors).min()>.025
        assert motors[-1].mode=='runonground'
