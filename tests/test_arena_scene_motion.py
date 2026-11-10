"""Independent material motion, crop jitter and unavailable visual evidence."""
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_scene_motion import GroundTextureMotion
from arena_support import VisualSupports
from arena_vision import Box


TEXTURE=cv2.GaussianBlur(np.random.default_rng(97).uniform(10,240,(80,1100)).astype(np.float32),(3,3),.6)


def scene(dx=0.,slope=0.,camera_y=0.):
    y,x=np.mgrid[:360,:640].astype(np.float32)
    top=250+slope*(x-320)+camera_y
    value=cv2.remap(TEXTURE,x-dx+200,y-top+20,cv2.INTER_LINEAR,borderMode=cv2.BORDER_WRAP)
    image=np.full((360,640),70,np.float32)
    image[y>=top]=value[y>=top]
    segment=dict(kind='platform',a=(4,250+slope*(4-320)+camera_y),
                 b=(630,250+slope*(630-320)+camera_y),confidence=.95)
    return np.repeat(image.astype(np.uint8)[:,:,None],3,axis=2),segment


def test_full_width_ground_uses_material_translation_not_stationary_crop():
    flow=GroundTextureMotion();supports=VisualSupports();player=Box(170,210,16,37)
    for i in range(7):
        image,segment=scene(-20*i)
        texture=flow.observe(image,[segment],i*.05,player)
        state=supports.observe([segment],player,i*.05,texture)
    assert state['scene_motion_source']=='ground_texture'
    assert state['scene_vx']==pytest.approx(-400,abs=5)
    assert all(s['left_clipped']and s['right_clipped']for s in state['segments'])


def test_rectified_sloping_ground_keeps_horizontal_speed_separate_from_camera_y():
    flow=GroundTextureMotion();a,sa=scene(slope=.2);b,sb=scene(-20,slope=.2,camera_y=5)
    flow.observe(a,[sa],0.,Box(170,210,16,37))
    result=flow.observe(b,[sb],.05,Box(170,210,16,37))
    assert result and result['vx']==pytest.approx(-400,abs=6)


def test_no_ground_or_no_texture_is_unknown_even_when_sky_moves():
    flow=GroundTextureMotion();a,sa=scene();b,sb=scene(-20)
    assert flow.observe(a,[dict(sa,kind='rope')],0.)is None
    assert flow.observe(b,[dict(sb,kind='rope')],.05)is None
    blank=np.zeros_like(a)
    assert flow.observe(blank,[sa],1.)is None
    assert flow.observe(blank,[sa],1.05)is None


def test_crop_near_border_cannot_claim_static_world_velocity():
    supports=VisualSupports();p=Box(170,210,16,37)
    for i in range(6):
        _,s=scene();s=dict(s,a=(4+i*.15,250),b=(630+i*.1,250),left_clipped=False,right_clipped=False)
        result=supports.observe([s],p,i*.04)
    assert not result['scene_motion_observed']
    assert result['scene_motion_source']is None


def test_reverse_fourier_peak_is_unknown_in_forward_arena():
    flow=GroundTextureMotion();a,sa=scene();b,sb=scene(20)
    flow.observe(a,[sa],0.,Box(170,210,16,37))
    assert flow.observe(b,[sb],.05,Box(170,210,16,37))is None


def test_truncated_endpoint_inside_the_crop_uncertainty_band_is_not_velocity():
    supports=VisualSupports()
    for i in range(6):
        segment=dict(kind='platform',a=(25+i*.2,250),b=(650,250),confidence=.95)
        result=supports.observe([segment],Box(170,210,16,37),i*.04)
    assert not result['scene_motion_observed']
