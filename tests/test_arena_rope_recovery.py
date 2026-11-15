"""Original down -> right rope recovery and observed versus forecast contacts."""
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_motion as motion
from arena_vision import (Box,Perception,advance_player,can_air_up,create_motion,
                          native_motion_box,transition_landing_phase)


def falling_down(root_height=2.,jumps=2):
    scale=40.;rope=260.
    active=dict(name='air_down',started=.9,height=root_height+3.55,lead=0.,
                offset_x=0.,offset_y=0.,width=.2,height_box=.2,destination='rope',
                requires_contact=True)
    return dict(time=1.,player=Box(176.,rope-root_height*scale-4,8.,8.),
                phase='flip_down',jumps=jumps,motion=active,rope=rope,terrain=None,
                scale_px=scale,stand_w=14.4,stand_h=37.44,vy=1120.,vx=0.,tracks=[])


def observation(actor,stamp,body,*,observed=True):
    support=dict(mode='rope',rope=260.,terrain=None,segments=[],
                 tracking_reference=(0.,0.),rope_segments=[])
    return actor._finish(np.zeros((360,640,3),np.uint8),stamp,body,[],
                         support_observation=support,player_observed=observed)


def test_airborne_right_during_down_recovers_above_without_spending_a_jump():
    obs=falling_down();actor=Perception();actor.visual_role=True;actor.jump_count=2
    assert can_air_up(obs)
    actor.action('jump',1.,obs)
    active=actor.active_motion
    assert active['name']=='air_up'and active['speed']==28.
    assert active['requires_contact']and actor.jump_count==2
    assert transition_landing_phase(active)=='rope_above'
    future=native_motion_box(obs,'air_up',.5)
    assert future.center[1]==pytest.approx(230.)
    assert future.h==pytest.approx(37.44)


def test_right_below_upper_rope_contact_reverses_at_original_eight_units():
    obs=falling_down(-.2)
    active=create_motion(obs,'air_up')
    assert active['speed']==-8.
    a=motion.point('air_up',.08,active);b=motion.point('air_up',.10,active)
    assert (b[1]-a[1])/.02==pytest.approx(8.)
    assert native_motion_box(obs,'air_up',1.).center[1]==pytest.approx(230.)
    assert motion.phase('air_up',1.,active)=='rope_above'


def test_recovery_is_not_a_third_jump_or_a_ground_roll_cancel():
    obs=falling_down()
    assert not can_air_up(dict(obs,phase='jump2_falling',motion=None))
    assert not can_air_up(dict(obs,rope=None))
    assert not can_air_up(dict(obs,motion=dict(obs['motion'],destination='ground')))
    assert not can_air_up(dict(obs,phase='rope_above',motion=None))


def test_down_and_up_preserve_exhausted_jumps_until_observed_rope_contact():
    actor=Perception();actor.visual_role=True;actor.jump_count=2
    airborne=dict(falling_down(),motion=None,phase='jump2_falling')
    actor.action('down',1.,airborne)
    assert actor.jump_count==2
    down=dict(airborne,motion=actor.active_motion,phase='flip_down')
    actor.action('jump',1.1,dict(down,time=1.1))
    assert actor.jump_count==2
    active=actor.active_motion
    assert active['name']=='air_up'
    # Timer completion is neither physical contact nor a replenished jump.
    pending=observation(actor,1.5,Box(176,180,8,8))
    assert pending['phase']=='flip_up'and pending['jumps']==2
    assert pending['motion']['contact_pending']
    standing=Box(172,211.28,16,37.44)
    inferred=observation(actor,1.525,standing,observed=False)
    assert inferred['jumps']==2 and inferred['motion']is not None
    assert not inferred['rope_contact_observed']
    landed=observation(actor,1.55,standing)
    assert landed['phase']=='rope_above'and landed['jumps']==0
    assert landed['motion']is None and landed['rope_contact_observed']


def test_planning_can_forecast_replenishment_without_an_input_receipt_claiming_it():
    obs=falling_down();active=create_motion(obs,'air_up');active['requires_contact']=True
    recovering=dict(obs,motion=active,phase='flip_up')
    submitted=advance_player(recovering,.5)
    predicted=advance_player(recovering,.5,predict_contact=True)
    assert submitted['phase']=='flip_up'and submitted['jumps']==2
    assert submitted['motion']['contact_pending']
    assert predicted['phase']=='rope_above'and predicted['jumps']==0
    assert predicted['landing_predicted']and not predicted['rope_contact_observed']
    assert not predicted['ground_contact_observed']


def test_future_landing_does_not_replenish_over_a_visible_rope_end():
    obs=falling_down()
    rope=dict(id=1,kind='rope',a=(0.,260.),b=(190.,260.),vx=-300.,vy=0.)
    obs.update(rope_segment=rope,rope_segments=[rope])
    active=create_motion(obs,'air_up');active['requires_contact']=True
    projected=advance_player(dict(obs,motion=active,phase='flip_up'),.5,predict_contact=True)
    assert projected['rope']is None and projected['jumps']==2
    assert projected['phase']=='flip_up'


def test_upper_recovery_duration_depends_on_height_not_the_fixed_lower_flip():
    low=create_motion(falling_down(2.),'air_up')
    high=create_motion(falling_down(4.),'air_up')
    assert motion.duration('air_up',high)-motion.duration('air_up',low)==pytest.approx(2/28)
    assert motion.duration('air_up',low)<motion.duration('rope_up')


def test_small_collider_near_rope_does_not_acknowledge_completion():
    actor=Perception();actor.visual_role=True;actor.jump_count=2
    actor.action('jump',1.,falling_down())
    pending=observation(actor,1.5,Box(176,226,8,8))
    assert pending['phase']=='flip_up'and pending['jumps']==2
    assert not pending['rope_contact_observed']


@pytest.mark.parametrize('initial,lead,speed,t,actual',[
    # Original UI v37 single_up_early, single_up_mid, single_up_late,
    # double_up_late and rope_down_up. Full raw hashes are in the prior.
    (2.1949548721,-.7,28.,.0333328247,1.2626523972),
    (.3283019066,-.7,-8.,.1000022888,.1983661652),
    (-.1383447647,-.7,-8.,.1000022888,-.3882999420),
    (-.5397958755,-.2102041245,-8.,.1000061035,-.2099409103),
    (.1566581726,-.2,-8.,.1000061035,.5433959961),
])
def test_rendered_original_reversals_fit_the_bounded_native_parameter_prior(initial,lead,speed,t,actual):
    parameters=dict(height=initial-.75,lead=lead,speed=speed,offset_x=0.,offset_y=0.,
                    width=.2,height_box=.2,destination='rope')
    predicted=initial+motion.point('air_up',t,parameters)[1]
    # Fixed 50 Hz and presented 60 Hz frames vary at the turn. This is a
    # calibrated ~7 px bound at scale 40, not an exact replay/no-hit claim.
    assert predicted==pytest.approx(actual,abs=.17)


def test_original_early_restored_body_counts_even_before_root_interpolation_settles():
    actor=Perception();actor.visual_role=True;actor.jump_count=2
    actor.action('jump',1.,falling_down(2.1949548721))
    # single_up_early has already restored the full native Role collider at
    # y=1.26265, although the visual root reaches y=.75 one frame later.
    body=Box(172,260-1.2626523972*40-18.72,16,37.44)
    landed=observation(actor,1.0333328247,body)
    assert landed['phase']=='rope_above'and landed['jumps']==0
    assert landed['rope_contact_observed']


def test_upper_contact_during_input_lead_selects_the_ascending_recovery_branch():
    active=create_motion(falling_down(1.),'air_up')
    assert active['height']>0 and active['height']+active['lead']<0
    assert active['speed']==-8.
