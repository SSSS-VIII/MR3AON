"""Ground correspondence, unavailable evidence and bounded camera prediction."""
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_scene_motion import GroundPatchMotion
from arena_support import VisualSupports
from arena_vision import Box


MATERIAL=cv2.GaussianBlur(np.random.default_rng(301).uniform(10,240,(100,1000)).astype(np.float32),(3,3),.6)


def scene(dx=0.,dy=0.,slope=.2,confidence=.3):
    y,x=np.mgrid[:360,:640].astype(np.float32)
    top=245+slope*(x-320)+dy-slope*dx
    texture=cv2.remap(MATERIAL,x-dx+150,y-top+20,cv2.INTER_LINEAR,borderMode=cv2.BORDER_WRAP)
    image=np.full((360,640),70,np.float32)
    image[y>=top]=texture[y>=top]
    line=dict(kind='platform',a=(4,float(top[0,4])),b=(630,float(top[0,630])),confidence=confidence)
    return np.repeat(image.astype(np.uint8)[:,:,None],3,axis=2),line


@pytest.mark.parametrize('dx,dy',[(-18.,-4.),(-43.,9.),(-80.,-15.)])
def test_weak_neural_proposals_require_actual_unique_pixel_translation(dx,dy):
    flow=GroundPatchMotion();a,sa=scene();b,sb=scene(dx,dy)
    assert flow.observe(a,[sa],1.)is None
    result=flow.observe(b,[sb],1.05)
    assert result is not None
    assert result['dx']==pytest.approx(dx,abs=.4)
    assert result['camera_dy']==pytest.approx(dy,abs=.4)
    assert result['span']>=96 and result['points']>=4


@pytest.mark.parametrize('kind',['rope','floating_platform'])
def test_moving_background_or_non_ground_cannot_be_camera_evidence(kind):
    flow=GroundPatchMotion();a,sa=scene();b,sb=scene(-25,6)
    flow.observe(a,[dict(sa,kind=kind)],1.)
    assert flow.observe(b,[dict(sb,kind=kind)],1.05)is None


def test_player_exclusion_is_two_dimensional_and_hud_stays_excluded():
    flow=GroundPatchMotion();_,s=scene(slope=0)
    airborne=flow.mask([s],Box(190,100,20,37))
    grounded=flow.mask([s],Box(190,215,20,37))
    assert airborne[260,200] and not grounded[260,200]
    assert not airborne[280,80] and not airborne[280,560]


def test_blank_or_repeated_ambiguous_material_is_unknown():
    _,s=scene(slope=0);flow=GroundPatchMotion()
    blank=np.full((360,640,3),40,np.uint8)
    flow.observe(blank,[s],1.)
    assert flow.observe(blank,[s],1.05)is None
    y,x=np.mgrid[:360,:640]
    tiles=((x%16<8)^(y%16<8)).astype(np.uint8)*180+30
    repeated=np.repeat(tiles[:,:,None],3,axis=2)
    flow=GroundPatchMotion();flow.observe(repeated,[s],1.)
    assert flow.observe(repeated,[s],1.05)is None


def test_parallax_above_a_blank_ground_proposal_cannot_supply_motion():
    a,s=scene(slope=0);b,_=scene(-30,0,slope=0)
    a[245:]=0;b[245:]=0
    flow=GroundPatchMotion();flow.observe(a,[s],1.)
    assert flow.observe(b,[s],1.05)is None


def test_conflicting_ground_translations_are_unknown():
    a,s=scene(slope=0);left,_=scene(-20,slope=0);right,_=scene(-50,slope=0)
    b=left.copy();b[:,320:]=right[:,320:]
    flow=GroundPatchMotion();flow.observe(a,[s],1.)
    assert flow.observe(b,[s],1.05)is None


@pytest.mark.parametrize('stamp',[1.,.9,1.3,float('nan')])
def test_unusable_image_interval_does_not_supply_a_velocity(stamp):
    a,s=scene();flow=GroundPatchMotion();flow.observe(a,[s],1.)
    assert flow.observe(a,[s],stamp)is None


def test_fresh_texture_camera_shift_is_opt_in_and_not_added_twice():
    _,s=scene(slope=0,confidence=.95)
    old=VisualSupports();new=VisualSupports(texture_camera_recovery=True)
    for supports in [old,new]:supports.associate([s],1.)
    shifted=dict(s,a=(4,255),b=(630,255))
    texture=dict(vx=-400.,dt=.05,camera_dy=10.)
    old.associate([shifted],1.05,texture);new.associate([shifted],1.05,texture)
    assert old.camera_motion_source=='support_track'
    assert new.camera_motion_source=='ground_patch'
    assert old.camera_y==pytest.approx(10.)
    assert new.camera_y==pytest.approx(10.)


def test_unmeasured_camera_gap_is_labelled_and_expires_without_fabricating_floor():
    _,s=scene();supports=VisualSupports(texture_camera_recovery=True)
    supports.associate([s],1.)
    supports.associate([s],1.05,dict(vx=-400.,dt=.05,camera_dy=-4.))
    supports.associate([s],1.10)
    assert supports.camera_y==pytest.approx(-8.)
    assert supports.camera_motion_source=='ground_patch_prediction'
    supports.associate([s],1.20)
    assert supports.camera_y==pytest.approx(-8.)
    assert supports.camera_motion_source is None
    supports.associate([s],1.25,dict(vx=-400.,dt=.05,camera_dy=-4.))
    before=supports.camera_y
    supports.associate([],1.30)
    assert supports.camera_y==before
    assert supports.camera_motion_source is None


@pytest.mark.parametrize('texture',[dict(vx=-400.,dt=.10,camera_dy=-4.),
                                   dict(vx=-400.,dt=.05,camera_dy=float('nan'))])
def test_stale_or_nonfinite_texture_is_not_camera_measurement(texture):
    _,s=scene();supports=VisualSupports(texture_camera_recovery=True)
    supports.associate([s],1.)
    supports.associate([s],1.05,texture)
    assert supports.camera_y==0.
    assert supports.camera_motion_source is None
