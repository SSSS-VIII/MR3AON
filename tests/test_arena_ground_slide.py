"""Original UI slide measurements, root/support geometry and visual feedback."""
from pathlib import Path
import sys
import pytest

pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_motion as motion
from arena_vision import Box,create_motion,player_future,advance_player,root_foot_box,landing_recovery
from arena_support import describe_terrain
from arena_policy import Avoider,touching
from arena_obb_detector import ObbPerception


def ground(slope=0.,end=1000.):
    segment=dict(id=1,kind='platform',a=(0,260+180*slope),b=(end,260-(end-180)*slope),vx=-640.,vy=0.,confidence=.95)
    terrain=describe_terrain([segment],segment,180)
    return dict(time=1.,player=Box(174.08,211.28,16.,37.44),phase='ground',motion=None,
                terrain=terrain,rope=None,scale_px=40.,stand_w=14.4,stand_h=37.44,
                jumps=0,tracks=[],vx=0.,scene_velocity_x=-640.,scene_motion_observed=True)


def test_original_slide_has_a_real_sixteen_pixel_body_and_slow_recovery():
    # Independent short UI probe, not generated from the implementation.
    assert motion.point('slide',.2)[0]==pytest.approx(1.279785,abs=.004)
    assert motion.point('slide',.2)[1:]==pytest.approx([-.25,-.156,.4,.4],abs=.0001)
    assert motion.point('slide',1.2)[0]==pytest.approx(.69583,abs=.004)
    assert motion.phase('slide',.7)=='ground'
    obs=ground();body=Avoider()._path(obs,'slide',.2)
    assert body.h==pytest.approx(16.,abs=.01)
    assert body.center[1]==pytest.approx(246.24,abs=.01)
    # This arrow intersects the actual body; the former 10 px box missed it.
    arrow=Box(body.center[0]-4,237,8,4)
    assert touching(body,arrow,margin=0,shape='box')
    assert not touching(Box(body.x,245,body.w,10),arrow,margin=0,shape='box')


def test_slide_root_advance_is_separate_and_projection_can_be_split():
    obs=ground();obs['motion']=create_motion(obs,'slide')
    first=advance_player(obs,.15);split=advance_player(first,.25);whole=advance_player(obs,.4)
    assert split['player'].center==pytest.approx(whole['player'].center,abs=.001)
    root=root_foot_box(whole)
    assert root.center[0]-root_foot_box(obs).center[0]==pytest.approx(1.04541*40,abs=.02)
    assert whole['player'].center[0]-root.center[0]==pytest.approx(1.809814*40,abs=.02)


def test_slide_follows_slope_at_movement_root_and_does_not_extend_floor():
    flat=ground();slope=ground(.25)
    a=Avoider()._path(flat,'slide',.2);b=Avoider()._path(slope,'slide',.2)
    # Terrain moves 128 px; root advances another 12.87 px. Body offset
    # (~49 px) must not be mistaken for that root's slope progress.
    assert b.center[1]-a.center[1]==pytest.approx(-.25*(128+.321869*40),abs=.02)
    short=ground(end=290);short['motion']=create_motion(short,'slide')
    after=advance_player(short,.3)
    assert after['phase']=='air_falling'and after['motion']is None
    assert after['player'].h>=short['stand_h']


def test_jump_interrupt_retains_original_parent_offset_until_ground_contact():
    obs=ground();obs['motion']=dict(name='slide',started=obs['time']-.2,base_speed=16.)
    jump=create_motion(obs,'jump1')
    assert jump['offset_carry_x']==pytest.approx(1.33435,abs=.002)
    assert motion.point('jump1',.1,jump)[0]==pytest.approx(1.38635,abs=.002)
    assert motion.point('jump1',.5,jump)[0]==pytest.approx(1.38635,abs=.002)
    landed=landing_recovery(jump,2.)
    assert motion.point('ground_recovery',.2,landed)[0]<1.1


def test_visual_slide_keeps_measured_body_and_support_uses_root():
    class Detector:
        last_ms=1.
        player=Box(174,211,16,38)
        def detect(self,rgb):
            return self.player,[],[dict(kind='platform',a=(0,260),b=(245,260),confidence=.95)],[]
    detector=Detector();perception=ObbPerception(detector);image=np.zeros((360,640,4),np.uint8)
    obs=perception.observe(image,1.)
    perception.action('slide',1.,obs)
    detector.player=Box(241,238,17,17)
    result=perception.observe(image,1.2)
    assert result['player']==detector.player
    assert result['phase']=='slide'
    # Body center has crossed the edge, original root remains on the platform.
    assert result['terrain']['at_player']
