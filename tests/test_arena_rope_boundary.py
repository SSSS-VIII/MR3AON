"""Finite support and original input identity at a rope/ground boundary."""
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Perception,advance_player,can_air_up,create_motion
from arena_mpc import start_action,advance
from arena_action_timing import commit_action,selected_primitive


def end_of_rope():
    rope=dict(id=1,kind='rope',a=(0.,260.),b=(185.,260.),vx=-300.,vy=0.)
    active=dict(name='air_down',started=.9,height=5.55,lead=0.,offset_x=0.,
                offset_y=0.,width=.2,height_box=.2,destination='rope',requires_contact=True)
    return dict(time=1.,player=Box(176.,176.,8.,8.),phase='flip_down',jumps=2,motion=active,
                rope=260.,rope_segment=rope,rope_segments=[rope],terrain=None,scale_px=40.,
                stand_w=14.4,stand_h=37.44,vy=1120.,vx=0.,tracks=[])


@pytest.mark.parametrize('name',['air_up','air_down'])
def test_new_candidate_cannot_replenish_after_its_visible_rope_has_passed(name):
    obs=end_of_rope()
    if name=='air_down':obs.update(phase='jump2_falling',motion=None)
    rolling=start_action(obs,name)
    assert not rolling['motion'].get('requires_contact',False)
    predicted=advance(rolling,.5)
    assert predicted['rope']is None and predicted['jumps']==2
    assert predicted['phase']in ('flip_up','flip_down')
    assert predicted['motion']['support_unconfirmed']
    assert not predicted.get('landing_predicted',False)


def test_existing_fixed_rope_primitive_still_completes_on_visible_rope():
    obs=end_of_rope();obs.update(player=Box(172.,211.28,16.,37.44),phase='rope_above',jumps=0,motion=None)
    obs['rope_segment']['b']=(640.,260.)
    down=advance(start_action(obs,'rope_down'),.4)
    assert down['phase']=='rope_below'and down['motion']is None
    up=advance(start_action(down,'rope_up'),.4)
    assert up['phase']=='rope_above'and up['motion']is None


def test_ack_after_support_loss_keeps_recovery_key_identity_and_spent_jumps():
    obs=end_of_rope();actor=Perception();actor.visual_role=True;actor.jump_count=2
    assert can_air_up(obs)
    result=commit_action(actor,obs,'jump',SimpleNamespace(device_ready_ns=1_050_000_000),
                         primitive=selected_primitive('jump','mpc_air_up'))
    assert result['submitted_primitive']=='air_up'
    assert result['committed_primitive']=='air_up'
    assert result['support_unconfirmed']
    assert actor.active_motion['requires_contact']and actor.jump_count==2
    projected=advance_player(dict(obs,time=1.1,motion=actor.active_motion,phase='flip_up'),.5,predict_contact=True)
    assert projected['jumps']==2 and projected['motion']is not None


def test_ack_retains_the_chosen_extrapolated_target_even_if_last_pixels_precede_it():
    latest=end_of_rope();latest['rope_segment'].update(a=(185.,260.),b=(195.,260.))
    latest['rope']=None
    assert not can_air_up(latest)
    planned=advance_player(latest,.03)
    assert can_air_up(planned)
    actor=Perception();actor.visual_role=True;actor.jump_count=2
    result=commit_action(actor,latest,'jump',SimpleNamespace(device_ready_ns=1_100_000_000),
                         primitive='air_up',planned=planned)
    assert result['committed_primitive']=='air_up'and result['support_unconfirmed']
    assert actor.jump_count==2


def test_uncertain_rope_recovery_resolves_only_at_real_full_body_ground_contact():
    obs=end_of_rope();actor=Perception();actor.visual_role=True;actor.jump_count=2
    commit_action(actor,obs,'jump',SimpleNamespace(device_ready_ns=1_050_000_000),primitive='air_up')
    support=dict(mode='ground',rope=None,terrain=dict(y=253.,at_player=True,samples=[],speed=300.,edge=None,landing=None),
                 segments=[],tracking_reference=(0.,0.),rope_segments=[])
    pixels=np.zeros((360,640,3),np.uint8);body=Box(172.,211.28,16.,37.44)
    inferred=actor._finish(pixels,1.3,body,[],support_observation=support,player_observed=False)
    assert inferred['jumps']==2 and inferred['motion']is not None
    small=actor._finish(pixels,1.35,Box(176.,226.,8.,8.),[],support_observation=support)
    assert small['jumps']==2 and small['motion']is not None
    landed=actor._finish(pixels,1.4,body,[],support_observation=support)
    assert landed['phase']=='ground'and landed['jumps']==0 and landed['motion']is None
    assert landed['ground_contact_observed']


def test_later_observed_rope_to_ground_change_also_clears_only_actual_contact():
    obs=end_of_rope();obs['rope_segment']['b']=(640.,260.)
    actor=Perception();actor.visual_role=True;actor.jump_count=2
    actor.action('jump',1.,obs)
    assert not actor.active_motion.get('support_unconfirmed')
    support=dict(mode='ground',rope=None,terrain=dict(y=253.,at_player=True,samples=[],speed=300.,edge=None,landing=None),
                 segments=[],tracking_reference=(0.,0.),rope_segments=[])
    pixels=np.zeros((360,640,3),np.uint8)
    pending=actor._finish(pixels,1.1,Box(176.,180.,8.,8.),[],support_observation=support)
    assert pending['motion']['support_unconfirmed']and pending['jumps']==2
    landed=actor._finish(pixels,1.2,Box(172.,211.28,16.,37.44),[],support_observation=support)
    assert landed['phase']=='ground'and landed['jumps']==0 and landed['motion']is None


@pytest.mark.parametrize('action,reason,expected',[
    ('jump','mpc_air_up','air_up'),('jump','mpc_rope_up','rope_up'),
    ('jump','mpc_jump2','jump2'),('down','mpc_air_down','air_down'),
    ('slide','mpc_slide','slide'),('down','mpc_air_up',None),
    ('jump','under_rope_escape:1',None),('jump','mpc_wait',None),
])
def test_runner_primitive_mapping_preserves_key_semantics(action,reason,expected):
    assert selected_primitive(action,reason)==expected
