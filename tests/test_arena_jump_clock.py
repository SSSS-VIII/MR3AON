"""Actual compact poses may correct a first-jump clock; predictions may not."""
from pathlib import Path
from copy import deepcopy
import math
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_jump_clock import JumpClockFeedback
from arena_vision import Box
import arena_motion as motion


def observation(stamp,*,shift=.012,started=1.,anchor=None):
    scale=40.;reference=300+17*stamp
    active=stamp>=1.
    p=motion.point('jump1',max(0,stamp-1.+shift))if active else motion.point('jump1',0.)
    cy=reference-(4+p[1]+p[2])*scale
    result=dict(time=stamp,player=Box(180,cy-p[4]*scale/2,p[3]*scale,p[4]*scale),
                scale_px=scale,camera_reference_y=reference,camera_motion_source='support_track',
                player_predicted=False,terrain=None,rope=reference,
                rope_segments=[dict(a=[0,reference],b=[640,reference])],
                phase='jump1_rising'if active else'rope_above',jumps=int(active),
                motion=dict(name='jump1',started=started)if active else None)
    if anchor is not None:result['motion']['clock_anchor_started']=anchor
    return result


def primed(shift=.012):
    feedback=JumpClockFeedback()
    for t in(.92,.97,1.03,1.06):feedback.estimate(observation(t,shift=shift))
    return feedback


def test_actual_compact_motion_recovers_clock_despite_camera_translation():
    feedback=primed();obs=observation(1.09);before=deepcopy(obs)
    result=feedback.estimate(obs)
    assert result['applied']and result['shift_seconds']==pytest.approx(.012)
    assert result['fitted_error_px2']<1e-20
    assert result['original_error_px2']>0
    assert obs==before


@pytest.mark.parametrize('shift',[-.025,0.,.012,.03])
def test_independent_exact_curves_and_zero_shift_are_supported(shift):
    feedback=primed(shift)
    feedback.estimate(observation(1.09,shift=shift))
    result=feedback.estimate(observation(1.12,shift=shift))
    assert result['applied']and result['shift_seconds']==pytest.approx(shift)


def test_corrected_clock_keeps_immutable_ack_anchor_instead_of_compounding():
    feedback=primed();first=feedback.estimate(observation(1.09))
    later=feedback.estimate(observation(1.12,started=1-first['shift_seconds'],anchor=1.))
    assert later['anchor_started']==1.
    assert later['shift_seconds']==first['shift_seconds']


@pytest.mark.parametrize('change,reason',[
    ({'player_predicted':True},'no_actual_body'),
    ({'player':None},'no_actual_body'),
    ({'camera_motion_source':'own_jump_prior'},'camera_not_independent'),
    ({'camera_motion_source':'ground_patch_prediction'},'camera_not_independent'),
    ({'camera_motion_source':None},'camera_not_independent'),
    ({'rope':None},'not_flat_rope'),
    ({'terrain':{'at_player':True}},'not_flat_rope'),
    ({'scale_px':math.nan},'invalid_geometry'),
])
def test_estimates_and_nonvalidated_geometry_do_not_self_confirm(change,reason):
    feedback=primed();obs=observation(1.09);obs.update(change)
    result=feedback.estimate(obs)
    assert not result['applied']and result['reason']==reason
    assert not feedback.history


def test_a_hidden_slope_among_flat_segments_is_rejected():
    feedback=primed();obs=observation(1.09)
    obs['rope_segments'].append(dict(a=[50,200],b=[150,220]))
    assert feedback.estimate(obs)['reason']=='not_flat_rope'


def test_transitional_body_must_not_force_a_delayed_jump_clock():
    feedback=primed();obs=observation(1.09);p=obs['player']
    obs['player']=Box(p.x,p.y,p.w,.9*motion.DATA['stand_height']*obs['scale_px'])
    assert feedback.estimate(obs)['reason']=='compact_pose_unconfirmed'


def test_repeated_exposure_is_not_an_additional_pose_measurement():
    feedback=JumpClockFeedback();feedback.estimate(observation(1.03))
    count=len(feedback.history)
    assert feedback.estimate(observation(1.03))['reason']=='repeated_or_old_exposure'
    assert len(feedback.history)==count


def test_second_jump_and_late_first_jump_are_outside_validation_scope():
    feedback=primed();obs=observation(1.09);obs['motion']['name']='jump2'
    assert feedback.estimate(obs)['reason']=='not_first_jump'
    assert feedback.estimate(observation(1.3))['reason']=='outside_entry_window'


def test_previous_jump_samples_cannot_be_relabelled_as_the_new_first_jump():
    feedback=primed();obs=observation(1.09);obs['motion']['started']=1.07
    assert feedback.estimate(obs)['reason']=='short_actual_history'


def test_observer_installs_fit_without_rewriting_ack_or_consuming_jump_twice():
    import numpy as np
    from types import SimpleNamespace
    from arena_obb_detector import ObbPerception
    from arena_input_timeline import OwnInputTimeline
    from arena_projection import SCALE
    class Detector:
        profile={'classes':[]};last_ms=0.;confidence=.25
        stamp=.9
        def detect(self,rgb):
            point=motion.point('jump1',max(0,self.stamp-1.+.012))if self.stamp>=1. else motion.point('jump1',0.)
            cy=250-(.75+point[1]+point[2])*SCALE
            return (Box(180,cy-point[4]*SCALE/2,point[3]*SCALE,point[4]*SCALE),[],
                    [dict(kind='rope',a=(0,250),b=(640,250),confidence=.99)],[])
    class Fit:
        def estimate(self,obs):
            if not obs.get('motion')or obs['time']>=1.13:return {'applied':False}
            active=obs['motion']
            return dict(applied=True,anchor_started=active.get('clock_anchor_started',active['started']),shift_seconds=.012)
    detector=Detector();actor=ObbPerception(detector);actor.jump_clock_feedback=Fit()
    timeline=OwnInputTimeline(actor);actor.input_timeline=timeline
    image=np.zeros((360,640,3),np.uint8)
    timeline.observe(image,.9)
    event=timeline.record('jump',SimpleNamespace(device_ready_ns=983333333),primitive='jump1')
    for stamp in(1.1,1.14):
        detector.stamp=stamp
        result=timeline.observe(image,stamp)
        assert result['motion']['clock_anchor_started']==event.estimated_consumption
        assert result['motion']['started']==pytest.approx(event.estimated_consumption-.012)
        assert actor.active_motion==timeline.observed_cursor.active_motion==result['motion']
        assert actor.last_action==event.estimated_consumption
        assert actor.jump_count==timeline.observed_cursor.jump_count==1
        assert not result['rope_contact_observed']and not result['ground_contact_observed']
    assert timeline.events==(event,)and timeline.consumed==1
