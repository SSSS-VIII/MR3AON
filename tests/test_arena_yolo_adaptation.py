"""Collider targets, perspective decoding and visual-state regressions."""
import sys
from pathlib import Path
import pytest

pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_projection import sphere_plane,capsule_plane,FOCAL,CAMERA
from arena_vision import Box,Detection,Tracker
from arena_yolo_detector import YoloPerception


def projected_bounds(x,y,r,half_y=None):
    """Independent pinhole projection of all eight world AABB corners."""
    z=CAMERA['player_plane_depth'];half_y=r if half_y is None else half_y
    points=np.array([[CAMERA['center_x']+FOCAL*a/c,CAMERA['center_y']+FOCAL*b/c]
                     for a in(x-r,x+r)for b in(y-half_y,y+half_y)for c in(z-r,z+r)])
    lo=points.min(0);hi=points.max(0)
    return Box(*lo,*(hi-lo))


@pytest.mark.parametrize('x,y,r',[(-4,1,.3),(6,-2,.45),(0,0,.1),(.03,-.1,.3),(-2,3,.6)])
def test_sphere_projection_recovers_gameplay_cross_section(x,y,r):
    actual=sphere_plane(projected_bounds(x,y,r));scale=FOCAL/CAMERA['player_plane_depth']
    assert actual.center==pytest.approx((CAMERA['center_x']+x*scale,CAMERA['center_y']+y*scale),abs=1e-7)
    assert actual.w==pytest.approx(2*r*scale,abs=1e-7)
    assert actual.h==pytest.approx(actual.w)


@pytest.mark.parametrize('x,y,r,h',[(-3,1,.18,.468),(0,0,.1,.1),(5,-2,.2,.468),(.05,.1,.2,.5)])
def test_role_capsule_projection_preserves_height_and_radius(x,y,r,h):
    actual=capsule_plane(projected_bounds(x,y,r,h));scale=FOCAL/CAMERA['player_plane_depth']
    assert actual.center==pytest.approx((CAMERA['center_x']+x*scale,CAMERA['center_y']+y*scale),abs=1e-7)
    assert (actual.w,actual.h)==pytest.approx((2*r*scale,2*h*scale),abs=1e-7)


def test_velocity_estimator_retains_slow_motion_but_suppresses_jitter():
    moving=Tracker(adaptive=True);jitter=Tracker(adaptive=True)
    for i in range(10):
        t=i*.025
        moving.update([Detection(Box(550-500*t,130+24*t,24,24),'spider',.93)],t,(180,260))
        jitter.update([Detection(Box(550-500*t,130+(-1)**i*.3,24,24),'spider',.93)],t,(180,260))
    assert moving.tracks[0].vy==pytest.approx(24,abs=.01)
    assert jitter.tracks[0].vy==0


def test_detected_role_position_is_not_overwritten_by_commanded_motion():
    class Detector:
        last_ms=0
        def detect(self,rgb):return Box(170,220,14,25),[]
    perception=YoloPerception(Detector());perception.support_mode='rope'
    perception.last_rope_hint=1
    perception.active_motion={'name':'jump1','started':.9}
    perception.motion_origin={'x':180,'y':-30,'scale':40,'stand_w':14,'stand_h':37}
    result=perception.observe(np.full((360,640,3),128,np.uint8),1)
    assert result['player']==Box(170,220,14,25)
    assert result['detector']=='fine_tuned_yolo26n'


def test_bouncing_future_remains_above_floor_and_preserves_retimed_velocity():
    from arena_object_motion import bounce_state
    from arena_vision import Track
    t=Track(1,Box(450,200,36,36),'pinball',.93,0,ballistic=True,
            gravity_up=320,gravity_down=320,floor_y=240,rebound_speed=280,vy=180)
    t.vx=-500
    y,v=bounce_state(218,180,.2,floor=240,gravity_up=320,gravity_down=320,rebound=280)
    assert y<240 and v<0  # The intervening floor contact reverses velocity.
    direct=t.future(.35);retimed=t.at(.2).future(.15)
    assert direct.center==pytest.approx(retimed.center)
    assert direct.center[1]<240


def test_planner_acts_on_imminent_collision_and_waits_for_distant_threat():
    from arena_mpc import MpcAvoider,advance,start_action
    from arena_vision import Track
    state=dict(player=Box(173,211,14,37),phase='rope_above',rope=260,time=1,jumps=0,
               scale_px=40,stand_w=14.4,stand_h=37.44,motion=None,terrain=None)
    threat=Track(1,Box(230,216,24,24),'pinball',.93,1,vx=-550,observations=6)
    assert MpcAvoider().uses_search(dict(state,tracks=[threat]))
    assert MpcAvoider().choose(dict(state,tracks=[threat]))[0]in ('down','jump')
    distant=Track(2,Box(600,216,24,24),'pinball',.93,1,vx=-550,observations=6)
    assert MpcAvoider().choose(dict(state,tracks=[distant]))[0]is None
    below=advance(start_action(state,'rope_down'),.32)
    assert below['phase']=='rope_below'and below['motion']is None
    above=advance(start_action(below,'rope_up'),.32)
    assert above['phase']=='rope_above'
    assert above['player'].center[1]==pytest.approx(state['player'].center[1],abs=.01)


def test_swept_collision_detects_crossing_between_two_clear_frames():
    from arena_mpc import swept_distance
    p=Box(170,210,14,37)
    before=np.array([[140.,228.,12.,12.]])
    after=np.array([[215.,228.,12.,12.]])
    assert abs(before[0,0]-p.center[0])>19
    assert abs(after[0,0]-p.center[0])>19
    assert swept_distance(p,p,before,after,0)[0]<1
    clear=np.array([[215.,140.,12.,12.]])
    assert swept_distance(p,p,clear,clear,0)[0]>1


def test_role_association_follows_dragged_character_outside_old_screen_roi():
    from types import SimpleNamespace
    from arena_yolo_detector import YoloDetector
    detector=object.__new__(YoloDetector);detector.player_x=180;detector.options={}
    class Data:
        def __init__(self,rows):self.rows=rows
        def cpu(self):return self
        def numpy(self):return np.asarray(self.rows,float)
    class Model:
        def __init__(self,x):self.x=x
        def predict(self,image,**options):
            return [SimpleNamespace(boxes=SimpleNamespace(data=Data([
                [self.x-8,211,self.x+8,250,.85,0],
                [580,211,600,240,.98,0]])))]
    for x in(180,230,280,330,380,430,480):
        detector.model=Model(x)
        player,_=detector.detect(np.zeros((360,640,3),np.uint8))
        assert player is not None and abs(player.center[0]-x)<5


def test_tracking_audit_compares_same_class_in_the_same_geometry():
    from arena_vision_dataset import native_box,match
    from arena_vision import Track
    raw=projected_bounds(5,1,.3)
    obj={'name':'EnemySpider(Clone)','type':'EnemySpider',
         'colliders':[{'type':'SphereCollider','box':[raw.x,raw.y,raw.x+raw.w,raw.y+raw.h]}]}
    actual=native_box(obj,plane=True)
    assert actual.w<native_box(obj).w
    wrong=Track(1,actual,'eye_enemy',.93,0)
    assert not match([wrong],{2:(obj,actual)},semantic=True)
    right=Track(1,actual,'spider',.93,0)
    assert 2 in match([right],{2:(obj,actual)},semantic=True)


def test_delay_projection_advances_flip_and_landing_state_with_geometry():
    from arena_vision import extrapolate,native_motion_box
    state=dict(time=1,player=Box(173,211,14.4,37.44),phase='rope_above',rope=260,
               scale_px=40,stand_w=14.4,stand_h=37.44,motion=None,jumps=0,tracks=[],terrain=None)
    start=1
    half=dict(state,time=1.2,player=native_motion_box(state,'rope_down',.2),
              motion=dict(name='rope_down',started=start),phase='flip_down')
    done=extrapolate(half,1.32)
    assert done['phase']=='rope_below'and done['motion']is None and done['jumps']==0
    air=dict(state,time=1.65,player=native_motion_box(state,'jump1',.65),
             motion=dict(name='jump1',started=start),phase='jump1_falling',jumps=1)
    landed=extrapolate(air,1.9)
    assert landed['phase']=='rope_above'and landed['motion']is None and landed['jumps']==0


def test_occluded_ball_camera_shift_moves_floor_with_predicted_body():
    from arena_vision import Track
    tracker=Tracker(adaptive=True)
    t=Track(1,Box(450,200,36,36),'pinball',.93,0,ballistic=True,
            gravity_up=320,gravity_down=320,floor_y=240,rebound_speed=280,vy=180,
            vx=-500,reference=(180,260))
    tracker.tracks=[t]
    predicted=tracker.update([],.1,(180,230))[0]
    assert predicted.floor_y==210
    assert predicted.reference==(180,230)
    original=t.future(.3);shifted=predicted.future(.2)
    assert shifted.center==pytest.approx((original.center[0],original.center[1]-30))
    assert t.floor_y==240  # Retained last-seen state stays in its original frame.
