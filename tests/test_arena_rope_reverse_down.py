"""Native state4 -> state3 on visible plain rope, with delayed input identity."""
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_motion as motion
from arena_vision import (Box,Perception,advance_player,can_air_down,can_reverse_rope_up,
                          create_motion,transition_speed)
from arena_action_timing import commit_action,selected_primitive
from arena_mpc import MpcAvoider,start_action,advance


def upward(root_height=0.,*,fast=False,finite=False):
    rope=dict(id=1,kind='rope',a=(0.,260.),b=(185. if finite else 640.,260.),vx=-300.,vy=0.)
    active=dict(name='air_up',started=.9,height=10. if fast else -1.5,lead=0.,
                speed=28. if fast else -8.,offset_x=0.,offset_y=0.,width=.2,height_box=.2,
                destination='rope',requires_contact=True)
    return dict(time=1.,player=Box(176.,260.-root_height*40.-4.,8.,8.),phase='flip_up',
                jumps=2,motion=active,rope=260.,rope_segment=rope,rope_segments=[rope],
                terrain=None,scale_px=40.,stand_w=16.,stand_h=37.44,vy=-320.,vx=0.,tracks=[])


def actual(actor,stamp,body,*,observed=True):
    return actor._finish(np.zeros((360,640,3),np.uint8),stamp,body,[],player_observed=observed,
        support_observation=dict(mode='rope',rope=260.,terrain=None,segments=[],
                                 tracking_reference=(0.,0.),rope_segments=[]))


def test_reverse_plain_rope_up_uses_eight_and_keeps_both_spent_jumps():
    obs=upward();actor=Perception();actor.visual_role=True;actor.jump_count=2
    assert can_air_down(obs)and can_reverse_rope_up(obs)
    actor.action('down',1.,obs)
    active=actor.active_motion
    assert active['name']=='air_down'and active['speed']==8.
    assert active['redirected_from']=='air_up'and active['requires_contact']
    assert actor.jump_count==2 and active['lead']>0
    assert transition_speed(active)==8.
    a=motion.point('air_down',.04,active);b=motion.point('air_down',.06,active)
    assert (b[1]-a[1])/.02==pytest.approx(-8.)
    assert 'air_down'in MpcAvoider()._options(obs,1.)


def test_original_airborne_height_branch_still_uses_twenty_eight():
    active=create_motion(upward(8.,fast=True),'air_down')
    assert active['speed']==28.
    assert active['lead']<0
    assert transition_speed(active)==28.


def test_speed_branch_checks_height_after_input_lead_not_only_current_height():
    # Current root is above upper rope contact, but the former state4 continues
    # descending during input lead and reaches the ordinary eight-unit branch.
    active=create_motion(upward(6.,fast=True),'air_down')
    assert active['speed']==8.


def test_existing_jump_down_keeps_original_twenty_eight_branch():
    obs=upward(3.4)
    obs.update(phase='jump1_falling',jumps=1,motion=None,vy=100.)
    active=create_motion(obs,'air_down')
    assert transition_speed(active)==28.
    assert 'redirected_from'not in active


@pytest.mark.parametrize('initial,lead,actual',[
    (-.39582061767578125,.28,-.6241798400878906),
    (.13740158081054688,.28,-.1974029541015625),
    (.564178466796875,.75-.564178466796875,.23582077026367188),
    (1.884765625,-.98,.30258750915527344),
])
def test_original_low_middle_top_and_airborne_reverse_displacements(initial,lead,actual):
    # Original rope_low/mid/top_reverse and double_roundtrip at input+0.1s.
    # The 50Hz physics/60Hz presentation phase is bounded, not an exact replay.
    parameters=dict(height=initial+.75,lead=lead,speed=8.,input_delay=motion.DATA['air_down']['reverse_input_delay'],
                    offset_x=0.,offset_y=0.,width=.2,height_box=.2,destination='rope')
    assert initial+motion.point('air_down',.1,parameters)[1]==pytest.approx(actual,abs=.12)


def test_fixed_rope_up_can_reverse_but_ground_platform_or_missing_line_cannot():
    obs=upward();obs['motion']=dict(name='rope_up',started=.95,requires_contact=True)
    assert can_air_down(obs)
    active=create_motion(obs,'air_down')
    assert active['speed']==8. and active['redirected_from']=='rope_up'
    assert not can_air_down(dict(obs,rope=None))
    assert not can_air_down(dict(obs,terrain={'source':'neural_segments'}))
    assert not can_air_down(dict(obs,motion=dict(obs['motion'],destination='ground')))
    assert not can_air_down(dict(obs,phase='flip_down'))
    obs['rope_segment']['b']=(170.,260.)
    assert not can_air_down(obs)


@pytest.mark.parametrize('slope_at',['selected','other_piece','list_without_selected'])
def test_new_reverse_rejects_a_visible_slope_in_selected_or_other_rope_piece(slope_at):
    obs=upward()
    slope=dict(id=2,kind='rope',a=(640.,260.),b=(900.,290.),vx=-300.,vy=0.)
    if slope_at=='selected':
        obs['rope_segment']['b']=(640.,290.)
    else:
        obs['rope_segments'].append(slope)
        if slope_at=='list_without_selected':obs.pop('rope_segment')
    assert not can_reverse_rope_up(obs)
    assert not can_air_down(obs)
    assert 'air_down'not in MpcAvoider()._options(obs,1.)


def test_scalar_legacy_flat_rope_and_bounded_endpoint_noise_still_allow_reverse():
    obs=upward()
    legacy=dict(obs,rope_segment=None,rope_segments=[])
    assert can_reverse_rope_up(legacy)
    obs['rope_segment']['b']=(640.,260.5)
    assert can_reverse_rope_up(obs)
    # Even a long shallow slope is not known flat from a cropped local height.
    obs['rope_segment']['b']=(640.,262.)
    assert not can_reverse_rope_up(obs)


def test_ordinary_jump_down_remains_available_on_a_sloping_rope():
    obs=upward(3.4)
    obs['rope_segment']['b']=(640.,290.)
    obs.update(phase='jump1_falling',jumps=1,motion=None,vy=100.)
    assert can_air_down(obs)
    active=create_motion(obs,'air_down')
    assert transition_speed(active)==28. and 'redirected_from'not in active
    assert 'air_down'in MpcAvoider()._options(obs,1.)


def test_variable_down_speed_and_delay_control_duration_and_full_future_geometry():
    obs=upward();a=create_motion(obs,'air_down');b=dict(a,speed=28.)
    assert motion.duration('air_down',a)>motion.duration('air_down',b)
    delayed=dict(a,input_delay=.04)
    assert motion.duration('air_down',delayed)-motion.duration('air_down',a)==pytest.approx(.04-a['input_delay'])
    early=motion.point('air_down',.02,delayed)
    assert early[1]==pytest.approx(a['lead']*.5)
    actor=Perception();actor.visual_role=True;actor.jump_count=2;actor.action('down',1.,obs)
    pending=actual(actor,1.5,Box(176,284,8,8))
    assert pending['phase']=='flip_down'and pending['jumps']==2
    body=Box(172,271.28,16,37.44)
    inferred=actual(actor,1.55,body,observed=False)
    assert inferred['jumps']==2 and inferred['motion']is not None
    landed=actual(actor,1.6,body)
    assert landed['phase']=='rope_below'and landed['jumps']==0
    assert landed['motion']is None and landed['rope_contact_observed']


def test_mpc_forecast_and_input_projection_do_not_share_landing_confirmation():
    obs=upward();active=create_motion(obs,'air_down');active['requires_contact']=True
    obs=dict(obs,motion=active,phase='flip_down')
    predicted=advance_player(obs,.3,predict_contact=True)
    committed=advance_player(obs,.3)
    assert predicted['jumps']==0 and predicted['landing_predicted']
    assert not predicted['rope_contact_observed']
    assert committed['jumps']==2 and committed['motion']['contact_pending']


def test_finite_rope_end_never_replenishes_reversed_down():
    predicted=advance(start_action(upward(finite=True),'air_down'),.3)
    assert predicted['rope']is None and predicted['jumps']==2
    assert predicted['phase']=='flip_down'and predicted['motion']['support_unconfirmed']


def test_ack_past_end_keeps_selected_reverse_down_and_does_not_drop_input():
    obs=upward(finite=True);actor=Perception();actor.visual_role=True;actor.jump_count=2
    result=commit_action(actor,obs,'down',SimpleNamespace(device_ready_ns=1_050_000_000),
                         primitive=selected_primitive('down','mpc_air_down'),planned=obs)
    assert result['submitted_primitive']=='air_down'
    assert result['committed_primitive']=='air_down'and result['support_unconfirmed']
    assert actor.jump_count==2 and actor.active_motion['requires_contact']
    assert actor.active_motion['redirected_from']=='air_up'
    projected=advance_player(dict(obs,time=1.1,motion=actor.active_motion,phase='flip_down'),.5,predict_contact=True)
    assert projected['jumps']==2 and projected['motion']is not None


def test_fixed_up_pending_contact_keeps_its_up_direction_and_can_reverse():
    obs=upward();actor=Perception();actor.visual_role=True;actor.jump_count=2
    actor.active_motion=dict(name='rope_up',started=.7,requires_contact=True)
    actor.motion_origin=dict(scale=40.,stand_w=16.,stand_h=37.44,x=180.,y=0.)
    pending=actual(actor,1.,Box(176.,246.,8.,8.))
    assert pending['phase']=='flip_up'and pending['jumps']==2
    assert can_reverse_rope_up(pending)


def test_uncertain_reversed_down_resolves_at_real_ground_without_replenishing_on_inference():
    obs=upward(finite=True);actor=Perception();actor.visual_role=True;actor.jump_count=2
    commit_action(actor,obs,'down',SimpleNamespace(device_ready_ns=1_050_000_000),primitive='air_down')
    support=dict(mode='ground',rope=None,terrain=dict(y=253.,at_player=True,samples=[],speed=300.,edge=None,landing=None),
                 segments=[],tracking_reference=(0.,0.),rope_segments=[])
    pixels=np.zeros((360,640,3),np.uint8);body=Box(172.,211.28,16.,37.44)
    inferred=actor._finish(pixels,1.3,body,[],support_observation=support,player_observed=False)
    assert inferred['jumps']==2 and inferred['motion']is not None
    landed=actor._finish(pixels,1.4,body,[],support_observation=support)
    assert landed['phase']=='ground'and landed['jumps']==0 and landed['motion']is None
    assert landed['ground_contact_observed']
