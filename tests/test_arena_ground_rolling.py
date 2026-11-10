"""Airborne ground decisions search native cancellation/landing actions together."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_mpc import MpcAvoider,start_action,advance
from arena_vision import Box,Track,can_air_down
from arena_support import describe_terrain


def falling():
    floor=dict(id=1,kind='platform',a=(0,260),b=(640,260),vx=-500.,vy=0.)
    return dict(time=1.,player=Box(172,110,16,37),phase='jump2_falling',jumps=2,motion=None,
                terrain=describe_terrain([floor],floor,180),rope=None,scale_px=40.,vy=100.,
                stand_w=16.,stand_h=37.,tracks=[Track(1,Box(250,120,30,30),'trap',.95,1,observations=6,vx=-500)])


def test_ground_airborne_search_can_cancel_second_jump_and_then_jump_from_landing():
    obs=falling();planner=MpcAvoider()
    assert planner.uses_search(obs)
    assert planner.choose(obs)==('down','mpc_air_down')
    landed=advance(start_action(obs,'air_down'),.3)
    assert landed['phase']=='ground'
    assert 'jump1'in planner._options(landed,landed['time'])
    # Standing still retains the existing native slide/edge controller.
    assert not planner.uses_search(dict(obs,phase='ground',jumps=0))


def test_ground_down_is_rejected_when_its_predicted_landing_is_past_the_edge():
    obs=falling();obs['terrain']['segments'][0]['b']=(200,260)
    assert not can_air_down(obs)
