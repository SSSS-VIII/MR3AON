"""Original rollToGround probe and airborne cancellation through real down input."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
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
    assert landed['player'].center[1]==pytest.approx(230-80*slope)
    actor=Perception();actor.action('down',1,obs)
    assert actor.active_motion['destination']=='ground'


def test_a_gap_is_not_a_valid_ground_down_landing_surface():
    obs=airborne();obs['terrain']['segments'][0]['a']=(250,260)
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
