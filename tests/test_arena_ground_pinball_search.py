"""Existing legal slide/jump search must cover grounded bouncing hazards."""
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
import json
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Track
from arena_mpc import MpcAvoider

DATA=json.loads((Path(__file__).parent/'fixtures/arena-ground-pinball-search.json').read_text())


def state(index):
    case=DATA['cases'][index];obs=deepcopy(case['input']);obs['player']=Box(**obs['player'])
    obs['tracks']=[Track(**{**{k:v for k,v in t.items()if k in{f.name for f in fields(Track)}},
                           'box':Box(**t['box'])})for t in obs['tracks']]
    planner=MpcAvoider();planner.ground_static_search=True;planner.ground_reserve_recovery=True
    planner.last_action=case['previous_action_time']
    return planner,obs


def test_grounded_ball_enters_existing_search_instead_of_reactive_slide():
    planner,obs=state(0)
    assert obs['phase']=='ground'and obs['terrain']is not None
    assert planner.uses_search(obs)
    assert {'jump1','slide'}<=set(planner._options(obs,obs['time']))


def test_real_slide_frame_can_jump_out_when_floor_detection_temporarily_disappears():
    planner,obs=state(2)
    assert obs['phase']=='slide'and obs['terrain']is None
    assert DATA['cases'][2]['saved']==[None,'action_transition']
    assert planner.uses_search(obs)
    assert 'jump1'in planner._options(obs,obs['time'])
    assert planner.choose(obs)==('jump','mpc_jump1')


def test_search_still_respects_the_original_early_slide_jump_restriction():
    planner,obs=state(1)
    assert planner.uses_search(obs)
    assert 'jump1'not in planner._options(obs,obs['time'])
    assert planner.choose(obs)[0]is None


def test_default_ground_search_stays_disabled_until_native_acceptance():
    planner,obs=state(2);planner.ground_static_search=False
    assert not planner.uses_search(obs)


@pytest.mark.parametrize('change',['weak','unconfirmed','different_hazard'])
def test_uncertain_ball_or_other_trap_does_not_expand_missing_floor_search(change):
    planner,obs=state(2)
    for track in obs['tracks']:
        if change=='weak':track.confidence=.01;track.confidence_history=[]
        elif change=='unconfirmed':track.observations=1
        else:track.kind='trap'
    assert not planner.uses_search(obs)
