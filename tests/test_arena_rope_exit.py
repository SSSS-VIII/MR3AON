"""Leaving below a visible rope endpoint is unsafe; a crop/seam is not an end."""
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Track,advance_player
from arena_mpc import MpcAvoider
from arena_support import VisualSupports,height


def observation(segments,below=True):
    return dict(time=1.,player=Box(172,271 if below else 211,16,37),phase='rope_below'if below else'rope_above',
        jumps=0,motion=None,vy=0,scale_px=40.,stand_w=16.,stand_h=37.,rope=260.,
        rope_segment=segments[0],rope_segments=segments,terrain=None,tracks=[])


def test_below_rope_returns_up_before_actual_endpoint_even_without_enemies():
    segment=dict(id=1,kind='rope',a=(0,260),b=(300,260),vx=-500.,vy=0.,right_clipped=False)
    obs=advance_player(observation([segment]),.08);planner=MpcAvoider()
    assert planner.uses_search(obs)
    assert planner.choose(obs)==('jump','mpc_rope_up')


def test_connected_rope_and_viewport_cut_do_not_create_an_invisible_gap():
    a=dict(id=1,kind='rope',a=(0,260),b=(300,260),vx=-500.,vy=0.,right_clipped=False)
    b=dict(id=2,kind='rope',a=(300,260),b=(640,260),vx=-500.,vy=0.,right_clipped=True)
    obs=observation([a,b]);future=advance_player(obs,.95)
    assert future['rope']==260 and future['rope_segment']['id']==2
    assert MpcAvoider().choose(obs)==(None,'mpc_wait')
    assert not MpcAvoider().rope_exit(observation([b]))


def test_clipped_short_edge_does_not_halve_scroll_velocity_or_invent_a_floor_end():
    supports=VisualSupports();player=Box(172,210,16,40)
    for i in range(6):
        t=i*.025
        result=supports.observe([dict(kind='platform',a=(100-500*t,260),b=(635,260),confidence=.9,
                                left_clipped=False,right_clipped=True)],player,t)
    s=result['segments'][0]
    assert s['vx']==pytest.approx(-500)
    assert result['terrain']['edge']is None
    assert height(s,180,2)==pytest.approx(260)
