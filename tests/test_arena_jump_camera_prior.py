"""Own jump dynamics can constrain camera motion, never certify contact."""
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_motion as motion
from arena_scene_motion import own_jump_camera_shift
from arena_support import VisualSupports
from arena_vision import Box
from arena_obb_detector import ObbPerception
from arena_projection import SCALE


def observation(t,active=None,camera=0.,base=240.):
    active=active or dict(name='jump1',started=10.)
    point=motion.point(active['name'],t-active['started'],active)
    w,h=point[3]*SCALE,point[4]*SCALE
    center=base-(point[1]+point[2])*SCALE+camera
    return dict(time=t,motion=active,phase=motion.phase(active['name'],t-active['started'],active),
                player=Box(180-w/2,center-h/2,w,h),player_predicted=False)


@pytest.mark.parametrize('camera',[-12.,0.,8.])
def test_jump_motion_and_camera_translation_have_separate_signs(camera):
    a=observation(10.20);b=observation(10.25,camera=camera)
    assert own_jump_camera_shift(a,b,SCALE)==pytest.approx(camera)


def test_jump2_entry_piecewise_carry_uses_only_the_acknowledged_parent():
    parent=dict(name='jump1',started=10.);p=motion.point('jump1',.24)
    active=dict(name='jump2',started=10.24,jump_entry=dict(parent=parent,age=.24,
        initial_point=[p[0],0.,p[2],p[3],p[4]]))
    a=observation(10.22,parent)
    b=observation(10.28,active,camera=6.,base=240-p[1]*SCALE)
    assert own_jump_camera_shift(a,b,SCALE)==pytest.approx(6.)
    active['jump_entry']['parent']=dict(name='jump1',started=9.)
    assert own_jump_camera_shift(a,b,SCALE)is None


@pytest.mark.parametrize('change',[dict(player=None),dict(player_predicted=True),
    dict(player=Box(170,200,60,90)),dict(phase='ground')])
def test_missing_predicted_or_inconsistent_body_never_supplies_camera(change):
    a=observation(10.20);b=observation(10.25);b.update(change)
    assert own_jump_camera_shift(a,b,SCALE)is None


def test_a_future_key_cannot_explain_an_older_image():
    a=observation(10.20);b=observation(10.25)
    b['motion']=dict(name='jump1',started=10.30)
    assert own_jump_camera_shift(a,b,SCALE)is None


@pytest.mark.parametrize('stamp',[10.20,10.15,10.40,float('nan')])
def test_invalid_or_stalled_image_interval_is_unknown(stamp):
    a=observation(10.20);b=observation(10.25);b['time']=stamp
    assert own_jump_camera_shift(a,b,SCALE)is None


def test_prior_does_not_extend_a_missed_jump_indefinitely():
    t=10.+motion.duration('jump1')+.5
    assert own_jump_camera_shift(observation(t),observation(t+.05),SCALE)is None


def test_camera_prior_works_without_lines_and_does_not_invent_a_floor():
    supports=VisualSupports();p=Box(170,100,16,37)
    supports.observe([],p,1.)
    result=supports.observe([],p,1.05,camera_prior=dict(dy=7.,dt=.05))
    assert result['tracking_reference'][1]==7.
    assert supports.camera_motion_source=='own_jump_prior'
    assert result['terrain']is None and result['rope']is None and result['segments']==[]


def test_scene_measurement_has_priority_over_the_own_jump_prior():
    supports=VisualSupports()
    old=dict(kind='rope',a=(0,240),b=(640,240),confidence=.95)
    supports.associate([old],1.)
    supports.associate([dict(old,a=(0,243),b=(640,243))],1.05,camera_prior=dict(dy=9.,dt=.05))
    assert supports.camera_y==pytest.approx(3.)
    assert supports.camera_motion_source=='support_track'


def test_selected_camera_velocity_compensates_floating_platforms():
    supports=VisualSupports()
    ground=dict(kind='platform',a=(80,250),b=(500,250),confidence=.3)
    floating=dict(kind='floating_platform',a=(100,150),b=(500,150),confidence=.9)
    p=Box(170,100,16,37)
    supports.observe([ground,floating],p,1.)
    current=[dict(ground,a=(60,260),b=(480,260)),dict(floating,a=(80,155),b=(480,155))]
    result=supports.observe(current,p,1.05,camera_prior=dict(dy=5.,dt=.05))
    target=next(s for s in result['segments']if s['kind']=='floating_platform')
    assert target['vy']==pytest.approx(0.)


class Detector:
    last_ms=0.
    profile={'classes':[]}

    def __init__(self,player,segments=()):self.player=player;self.segments=list(segments)

    def detect(self,rgb):return self.player,[],self.segments,[]


def observer(previous,current,*,prepared=True,segments=(),enabled=True):
    p=ObbPerception(Detector(current['player'],segments))
    p.jump_camera_recovery=enabled;p.last_observation=previous
    p.active_motion=current['motion'];p.jump_count=1
    p.motion_origin=dict(scale=SCALE,stand_h=motion.DATA['stand_height']*SCALE)
    p.supports.observe([],previous['player'],previous['time'])
    p.input_timeline=SimpleNamespace(prepared_stamp=current['time']if prepared else None)
    return p


def test_adapter_applies_prior_before_motion_estimation_without_resetting_jumps():
    a=observation(10.20);b=observation(10.25,camera=8.)
    p=observer(a,b)
    result=p.observe(np.zeros((360,640,3),np.uint8),b['time'])
    assert result['camera_motion_source']=='own_jump_prior'
    assert result['camera_reference_y']==pytest.approx(8.)
    assert result['jumps']==1 and result['motion']['name']=='jump1'
    assert result['terrain']is None and not result['ground_contact_observed']


@pytest.mark.parametrize('prepared,enabled',[(False,True),(True,False)])
def test_adapter_requires_image_time_cursor_and_internal_opt_in(prepared,enabled):
    a=observation(10.20);b=observation(10.25,camera=8.)
    p=observer(a,b,prepared=prepared,enabled=enabled)
    result=p.observe(np.zeros((360,640,3),np.uint8),b['time'])
    assert result['camera_reference_y']==0.
    assert result['jump_camera_prior']is None


def test_visible_actual_contact_cannot_be_absorbed_into_camera_prior():
    a=observation(10.45);b=observation(10.50)
    # The raw current capsule is standing at a visible rope, despite an old
    # jump cursor. It must remain independent evidence of actual contact.
    surface=b['player'].center[1]+.75*SCALE
    line=dict(kind='rope',a=(0,surface),b=(640,surface),confidence=.95)
    p=observer(a,b,segments=[line])
    result=p.observe(np.zeros((360,640,3),np.uint8),b['time'])
    assert result['jump_camera_prior']is None
