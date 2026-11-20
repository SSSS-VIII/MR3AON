"""An original two-metre step kills the role before its vertical link."""
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel
from arena_privileged_policy import InternalController

CASE=json.loads((Path(__file__).parent/'fixtures/arena-privileged-wall.json').read_text())


def test_native_wall_death_is_predicted_before_the_link_and_can_be_jumped_early():
    before,after=CASE['before'],CASE['after_without_keys']
    assert after['state']['health']==0
    assert after['state']['physics'].startswith('dieOnWater:')
    wall=next(r for r in before['terrain'] if r['kind'].startswith('link:'))
    assert wall['start']['x']>after['state']['position']['x']
    model=PlayerModel(before);times=np.linspace(0,1.8,217)
    assert not model.unsupported
    _,coast,_=model.trajectory(times)
    risk=model.terrain_clearances(coast)
    first=int(np.flatnonzero(risk<=0)[0])
    assert coast[first].x<wall['start']['x']
    proposal=InternalController().decide(before)
    assert proposal.reason=='approach_center_of_native_safe_window'
    assert proposal.evidence['window_choice']['action']=='jump'
    assert proposal.delay+.04<proposal.evidence['coast']['first_contact']
    for delta in (-.04,.04):
        _,states,valid=model.trajectory(times,((proposal.delay+delta,'jump'),))
        assert valid and model.terrain_clearances(states).min()>.025


def test_descending_vertical_link_does_not_become_a_wall_or_fictitious_floor():
    before=json.loads(json.dumps(CASE['before']))
    before['terrain']=[r for r in before['terrain'] if r['finish']['y']<r['start']['y']]
    model=PlayerModel(before)
    assert len(before['terrain'])==1
    assert not model.unsupported
    _,states,_=model.trajectory(np.linspace(0,1.8,217))
    assert np.isinf(model.terrain_clearances(states)).all()
