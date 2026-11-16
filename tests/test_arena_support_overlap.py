"""Pixel line splits must preserve overlapping material and real air gaps."""
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
import json
import sys
import pytest
pytest.importorskip('numpy')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_support import connected_height,joined_endpoints
from arena_vision import Box,Track
from arena_mpc import MpcAvoider,advance

DATA=json.loads((Path(__file__).parent/'fixtures/arena-overlapping-rope.json').read_text())


def observed():
    state=deepcopy(DATA['input']);state['player']=Box(**state['player'])
    state['tracks']=[Track(**{**{k:v for k,v in t.items()if k in{f.name for f in fields(Track)}},
                             'box':Box(**t['box'])})for t in state['tracks']]
    return state


def line(identity,a,b,kind='rope'):
    return dict(id=identity,kind=kind,a=a,b=b,vx=-300.,vy=0.)


def test_actual_overlapping_rope_does_not_end_under_the_runner():
    state=observed();a,b=state['rope_segments']
    assert not joined_endpoints(a,b)
    assert min(a['b'][0],b['b'][0])-max(a['a'][0],b['a'][0])>6
    future=advance(state,.2)
    assert future['rope']is not None
    assert future['phase']=='rope_below'and future['motion']is None


def test_saved_beam_no_longer_forces_a_collision_to_escape_a_false_rope_end():
    planner=MpcAvoider();planner.ground_static_search=True;planner.ground_reserve_recovery=True
    planner.last_action=DATA['previous_action_time']
    assert DATA['saved_decision']==['jump','mpc_rope_up']
    assert planner.choose(observed())==(None,'mpc_wait')


@pytest.mark.parametrize('kind',['rope','platform'])
def test_overlapping_sloped_static_material_can_be_followed_in_both_orders(kind):
    a=line(1,(0.,200.),(300.,230.),kind);b=line(2,(250.,225.),(600.,260.),kind)
    for segments in ([a,b],[b,a]):
        assert connected_height(segments,1,350.)==pytest.approx(235.)
        assert connected_height(segments,2,50.)==pytest.approx(205.)
        assert connected_height(segments,1,250.,.4)==pytest.approx(237.)


@pytest.mark.parametrize('other',[
    line(2,(307.,200.),(600.,200.)), # Actual gap beyond old endpoint tolerance.
    line(2,(250.,207.),(600.,207.)), # Different level.
    line(2,(250.,200.),(600.,270.)), # Crossing tangents disagree in the overlap.
    line(2,(250.,200.),(600.,200.),'platform'),
])
def test_real_gaps_levels_and_different_support_types_remain_disconnected(other):
    a=line(1,(0.,200.),(300.,200.))
    assert connected_height([a,other],1,400.)is None


def test_overlap_does_not_join_independent_moving_platforms():
    a=line(1,(0.,200.),(300.,200.),'floating_platform')
    b=line(2,(250.,200.),(600.,200.),'floating_platform');b['vy']=100.
    assert connected_height([a,b],1,400.)is None
