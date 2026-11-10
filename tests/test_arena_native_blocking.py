"""Original root foot/climbDistance movement probe differs from hurt geometry."""
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_motion as motion
from arena_vision import Box,root_foot_box
from arena_policy import VisualAvoider
from arena_support import VisualSupports,describe_terrain


def test_original_ninja_data_foot_and_climb_parameters_are_preserved():
    assert motion.DATA['blocking']['climb_distance']==pytest.approx(.8)
    assert motion.DATA['blocking']['foot_point']==pytest.approx(.75)
    obs=dict(player=Box(172,211.28,16,37.44),time=1,motion=None,scale_px=40.)
    assert root_foot_box(obs).center==pytest.approx((180-.052*40,260))


def test_hurt_capsule_clearing_a_raised_step_does_not_prove_root_foot_clearance():
    wall=dict(id=1,kind='platform',a=(250,180),b=(640,180),vx=-500.,vy=0.,confidence=.95,stamp=1)
    ground=dict(id=2,kind='platform',a=(0,260),b=(640,260),vx=-500.,vy=0.,confidence=.95,stamp=1)
    obs=dict(time=1,player=Box(172,211.28,16,37.44),phase='ground',rope=None,
             terrain=describe_terrain([ground],ground,180),visible_supports=[wall],tracks=[],
             motion=None,jumps=0,scale_px=40.,stand_w=16,stand_h=37.44,vy=0)
    policy=VisualAvoider()
    assert policy._risk(obs,'jump')[0]<policy._risk(obs,'none')[0]
    assert policy.choose(obs)[0]=='jump'


def test_one_cropped_endpoint_cannot_drag_common_static_flow_toward_zero():
    supports=VisualSupports();p=Box(172,210,16,40)
    for i in range(5):
        t=i*.025
        state=supports.observe([
            dict(kind='rope',a=(0,260),b=(400-600*t,260),confidence=.9,left_clipped=True,right_clipped=False),
            dict(kind='platform',a=(450-600*t,160),b=(636,160),confidence=.9,left_clipped=False,right_clipped=False)],p,t)
    assert state['scene_vx']==pytest.approx(-600)
    assert all(s['vx']==pytest.approx(-600)for s in state['segments'])
