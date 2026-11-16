"""Ground traps need continuous action planning, including slide interruption."""
import json
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_mpc import MpcAvoider
from arena_vision import Box,Track


def cases():
    payload=json.loads((Path(__file__).parent/'fixtures/arena-ground-static-search.json').read_text())
    for case in payload['cases']:
        obs=case['observation'];obs['player']=Box(**obs['player'])
        obs['tracks']=[Track(**dict(t,box=Box(**t['box'])))for t in obs['tracks']]
        yield obs,case['last_action']


def test_candidate_avoids_native_slide_commit_and_allows_later_jump_interrupt():
    standing,sliding=list(cases())
    old=MpcAvoider();old.last_action=standing[1]
    assert old.choose(standing[0])[0]=='slide'
    planner=MpcAvoider();planner.ground_static_search=True;planner.last_action=standing[1]
    assert planner.choose(standing[0])==(None,'mpc_wait')
    old=MpcAvoider();old.last_action=sliding[1]
    assert old.choose(sliding[0])==(None,'action_transition')
    planner=MpcAvoider();planner.ground_static_search=True;planner.last_action=sliding[1]
    assert planner.choose(sliding[0])==('jump','mpc_jump1')


def test_candidate_needs_visible_ground_static_hazard_and_body():
    obs,last=next(cases());planner=MpcAvoider();planner.ground_static_search=True
    assert planner.uses_search(obs)
    assert not MpcAvoider().uses_search(obs)
    assert not planner.uses_search(dict(obs,player=None))
    assert not planner.uses_search(dict(obs,tracks=[]))
    assert not planner.uses_search(dict(obs,terrain=dict(obs['terrain'],source='unknown')))
    enemies=[Track(t.id,t.box,'eye_enemy',.95,obs['time'],observations=5)for t in obs['tracks']]
    assert not planner.uses_search(dict(obs,tracks=enemies))


def test_search_keeps_native_input_cooldown_while_sliding():
    obs,last=list(cases())[1];planner=MpcAvoider();planner.ground_static_search=True
    assert 'jump1'in planner._options(obs,obs['time'])
    just_pressed=dict(obs,last_input_time=obs['time']-.05)
    assert planner._options(just_pressed,obs['time'])==[None]
