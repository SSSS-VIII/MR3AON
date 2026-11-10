"""Original rollToGround probe and airborne cancellation through real down input."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_motion as motion
from arena_vision import Box,can_air_down,create_motion,native_motion_box,advance_player,Perception
from arena_support import describe_terrain
from arena_policy import Avoider
from arena_mpc import start_action


def airborne(slope=0):
    floor=dict(id=1,kind='platform',a=(0,260+180*slope),b=(640,260-460*slope),vx=-200.,vy=0.)
    return dict(time=1.,player=Box(172,111.28,16,37.44),phase='jump2_falling',jumps=2,motion=None,
                terrain=describe_terrain([floor],floor,180),rope=None,scale_px=40.,vy=150.,
                stand_w=16.,stand_h=37.44,tracks=[])


@pytest.mark.parametrize('height,lead,t,delta,end',[
    (1.4045,.23505,.0498,-.6870,.0830),(2.41887,.01521,.0835,-1.8628,.1167)])
def test_original_ground_first_and_second_jump_down_samples(height,lead,t,delta,end):
    parameters=dict(height=height,lead=lead,offset_x=0,offset_y=0,width=.4,height_box=.936,destination='ground')
    assert motion.point('air_down',t,parameters)[1]==pytest.approx(delta,abs=.04)
    assert motion.duration('air_down',parameters)==pytest.approx(end,abs=.025)
    assert motion.phase('air_down',.4,parameters)=='ground'
    assert motion.point('air_down',.4,parameters)[4]==pytest.approx(.936)


@pytest.mark.parametrize('slope',[-.5,0,.5])
def test_ground_down_targets_the_top_surface_and_follows_its_slope(slope):
    obs=airborne(slope)
    assert can_air_down(obs)
    active=create_motion(obs,'air_down')
    assert active['destination']=='ground'
    assert active['surface_velocity']==pytest.approx(-5*slope)
    landed=advance_player(start_action(obs,'air_down'),.4)
    assert landed['phase']=='ground'and landed['motion']is None
    # Down changes the original collider X offset; the intercepted slope is
    # evaluated at the root, not the pre-input standing capsule center.
    assert landed['player'].center[1]==pytest.approx(230-(80-motion.DATA['stand_offset_x']*40)*slope)
    actor=Perception();actor.action('down',1,obs)
    assert actor.active_motion['destination']=='ground'


def test_a_gap_is_not_a_valid_ground_down_landing_surface():
    obs=airborne();obs['terrain']['segments'][0]['a']=(250,260)
    assert not can_air_down(obs)


def test_down_can_intercept_a_visible_platform_that_is_ahead_of_the_current_root():
    obs=airborne();s=obs['terrain']['segments'][0]
    s.update(a=(195,260),b=(250,260))
    assert can_air_down(obs)
    active=create_motion(obs,'air_down')
    assert active['contact_seconds']>.075  # Entry occurs before contact.
    landed=advance_player(start_action(obs,'air_down'),active['contact_seconds']+.02)
    assert landed['phase']=='ground'
    # A platform reached only after the role has already fallen below its top
    # is a wall, not a valid late teleport onto the surface.
    s.update(a=(225,260),b=(280,260))
    assert not can_air_down(obs)


def test_down_rejects_a_narrow_platform_that_has_passed_before_landing():
    obs=airborne();s=obs['terrain']['segments'][0]
    s.update(a=(160,260),b=(190,260))
    assert not can_air_down(obs)


def test_reactive_controller_can_cancel_an_airborne_jump_before_old_320ms_lock():
    class Threat(Avoider):
        def _risk(self,obs,action):
            from arena_vision import Track
            threat=Track(1,Box(200,100,20,20),'trap',.95,1)
            return (0,10,{})if action=='air_down'else (100,.12,{1:(.12,threat)})
    policy=Threat();policy.last_action=.85
    assert policy.choose(airborne())[0]=='down'
    policy=Threat();policy.last_action=.95
    assert policy.choose(airborne())==(None,'action_transition')


def test_native_down_waits_for_visible_contact_before_accepting_another_jump():
    actor=Perception();actor.visual_role=True
    obs=airborne();actor.action('down',1.,obs)
    support=dict(mode='ground',rope=None,terrain=obs['terrain'],segments=obs['terrain']['segments'],
                 tracking_reference=(0.,0.),rope_segments=[])
    rgba=np.zeros((360,640,3),np.uint8)
    # The estimated timer expired, but the real collider is still tiny and far
    # from contact. Do not invent a landing/cancel the native rollToGround.
    estimate=actor._finish(rgba,1.4,Box(176,160,8,8),[],support_observation=support)
    assert estimate['phase']=='flip_down'
    assert estimate['motion']['contact_pending']
    assert advance_player(estimate,.03)['phase']=='flip_down'
    assert advance_player(estimate,.03)['player'].center[1]>estimate['player'].center[1]+30
    # A missing detection extrapolated to standing contact is no acknowledgement.
    standing=Box(172,211.28,16,37.44)
    extrapolated=actor._finish(rgba,1.425,standing,[],support_observation=support,player_observed=False)
    assert extrapolated['motion']is not None
    landed=actor._finish(rgba,1.45,standing,[],support_observation=support)
    assert landed['phase']=='ground'and landed['motion']is None
    assert landed['ground_contact_observed']
    assert not extrapolated['ground_contact_observed']


def test_confirmed_landing_can_relaunch_before_a_short_platform_has_passed():
    obs=airborne();obs.update(player=Box(172,211.28,16,37.44),phase='ground',jumps=0,
                            ground_contact_observed=True)
    obs['terrain']['edge']=205
    policy=Avoider();policy.last_action=.84
    assert policy.choose(obs)==('jump','ground_edge')
    policy=Avoider();policy.last_action=.84
    assert policy.choose(dict(obs,ground_contact_observed=False))==(None,'action_transition')
    policy=Avoider();policy.last_action=.95
    assert policy.choose(obs)==(None,'action_transition')


def test_input_delay_projection_cannot_acknowledge_future_ground_contact():
    actor=Perception();actor.visual_role=True;obs=airborne();actor.action('down',1.,obs)
    active=dict(obs,motion=actor.active_motion,phase='flip_down')
    projected=advance_player(active,.4)
    assert projected['phase']=='flip_down'and projected['motion']['contact_pending']
