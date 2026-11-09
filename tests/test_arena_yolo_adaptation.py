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


def test_action_commit_uses_projected_landing_state_instead_of_old_jump_count():
    from arena_vision import Perception
    p=Perception();p.jump_count=1
    state=dict(time=1.8,player=Box(173,211,14.4,37.44),phase='rope_above',rope=260,
               scale_px=40,stand_w=14.4,stand_h=37.44,motion=None,jumps=0,terrain=None)
    p.action('jump',1.8,state)
    assert p.active_motion['name']=='jump1'and p.jump_count==1
    state.update(time=2.05,phase='jump1_rising',jumps=1,motion=p.active_motion)
    p.action('jump',2.05,state)
    assert p.active_motion['name']=='jump2'and p.jump_count==2


def test_state_head_uses_learned_ready_rush_classes_instead_of_colour_guess():
    from types import SimpleNamespace
    from arena_yolo_detector import YoloDetector
    detector=object.__new__(YoloDetector);detector.player_x=180;detector.options={};detector.state_classes=True
    class Data:
        def cpu(self):return self
        def numpy(self):return np.array([[400,150,430,180,.9,2],[450,150,480,180,.9,6],[500,150,530,180,.9,7]])
    class Model:
        def predict(self,image,**options):return[SimpleNamespace(boxes=SimpleNamespace(data=Data()))]
    detector.model=Model()
    _,objects=detector.detect(np.full((360,640,3),(200,20,20),np.uint8))
    assert [(o.arming,o.active)for o in objects]==[(False,False),(True,False),(False,True)]


def test_learned_ready_state_waits_then_predicts_native_dash_and_collider_growth():
    from arena_projection import SCALE
    from arena_vision import Track
    t=Track(1,Box(400,200,22,22),'eye_enemy',.9,0)
    t.update(Detection(t.box,'eye_enemy',.9,False,True,'ready'),1,(180,260))
    assert t.future(.2).center==pytest.approx(t.box.center)
    after=t.future(.4)
    assert after.center[0]==pytest.approx(t.box.center[0]-24*SCALE*.1)
    assert after.w==pytest.approx(22*1.3)
    assert t.at(.25).future(.15).center==pytest.approx(after.center)
    assert t.at(.32).future(.08).w==pytest.approx(after.w)
    t.update(Detection(Box(400,200,26,26),'eye_enemy',.9,False,True,'ready'),1.1,(180,260))
    assert t.future(.4).w==pytest.approx(22*1.3)  # Never compound the 30% scale.
    t.update(Detection(t.box,'spider',.9),1.1,(180,260))
    assert t.attack_phase is None  # A new class cannot inherit the dash model.


def test_identity_association_uses_dash_prediction_when_mean_velocity_still_lags():
    from arena_vision import Track
    from arena_projection import SCALE
    tracker=Tracker(adaptive=True)
    moving=Track(1,Box(400,200,28,28),'eye_enemy',.9,1,
                 vx=0,observations=8,reference=(180,260),attack_phase='rush',
                 rush_target_w=28,rush_target_h=28)
    tracker.tracks=[moving];tracker.next_id=2
    actual=Box(400-24*SCALE*.025,200,28,28)
    tracker.update([Detection(Box(400,200,28,28),'eye_enemy',.9),
                    Detection(actual,'eye_enemy',.9,True,False,'rush')],1.025,(180,260))
    retained=next(t for t in tracker.tracks if t.id==1)
    assert retained.box.x==pytest.approx(actual.x)


def test_batched_sweeps_keep_each_candidate_and_each_hazard_independent():
    from arena_mpc import swept_distances
    players=np.array([[177,228.5,14,37],[177,68.5,14,37],[177,224,8,8]],float)
    before=np.array([[140,228,12,12],[140,70,12,12]],float)
    after=np.array([[215,228,12,12],[215,70,12,12]],float)
    collisions=swept_distances(players,players,before,after,0)<1
    assert collisions.tolist()==[[True,False],[False,True],[True,False]]


def test_observed_stop_ends_old_entering_velocity_without_erasing_slow_motion():
    from arena_vision import Track
    fast=Track(1,Box(500,200,24,24),'eye_enemy',.9,0,adaptive_velocity=True)
    slow=Track(2,Box(500,200,24,24),'eye_enemy',.9,0,adaptive_velocity=True)
    for i,x in enumerate([500,477,454,431,431,431,431]):
        t=i*.025
        fast.update(Detection(Box(x,200,24,24),'eye_enemy',.9,False,False,'normal'),t,(180,260))
        slow.update(Detection(Box(500-50*t,200,24,24),'eye_enemy',.9,False,False,'normal'),t,(180,260))
    assert fast.horizontal_stopped and fast.future(.2).x==pytest.approx(431)
    assert not slow.horizontal_stopped and slow.vx==pytest.approx(-50,abs=.01)


def test_ready_onset_is_between_exposures_not_at_the_later_image():
    from arena_vision import Track
    t=Track(1,Box(400,200,22,22),'eye_enemy',.9,0)
    t.update(Detection(t.box,'eye_enemy',.9,False,False,'normal'),1.,(180,260))
    t.update(Detection(t.box,'eye_enemy',.9,False,True,'ready'),1.06,(180,260))
    assert t.ready_started==pytest.approx(1.03)
    assert t.ready_remaining==pytest.approx(.27)


def test_search_returns_to_upper_rope_after_threats_leave():
    from arena_mpc import MpcAvoider
    policy=MpcAvoider()
    obs=dict(player=Box(172,240,16,37),rope=219.,phase='rope_below',
             jumps=0,tracks=[],terrain=None,time=1.)
    assert policy.choose(obs)==(None,'clear')
    obs['time']=1.8
    assert policy.choose(obs)==('jump','neutral_above')


def test_visible_hazards_keep_tracking_while_role_is_outside_image():
    from arena_vision import Perception
    p=Perception();p.support_mode='rope';p.rope=260.;p.last_rope_hint=1.
    rgb=np.full((360,640,3),128,np.uint8)
    role=Box(172,210,16,37)
    def enemy(phase):return Detection(Box(440,210,22,22),'eye_enemy',.9,False,phase=='ready',phase)
    first=p._finish(rgb,1.,role,[enemy('normal')])
    missing=p._finish(rgb,1.1,None,[enemy('ready')])
    assert missing['player']is None and missing['phase']=='unknown'
    assert missing['tracks'][0].id==first['tracks'][0].id
    assert missing['tracks'][0].observations==2
    assert missing['tracks'][0].ready_started==pytest.approx(1.05)
    returned=p._finish(rgb,1.2,role,[enemy('ready')])
    assert returned['tracks'][0].observations==3
    assert returned['tracks'][0].ready_remaining==pytest.approx(.15)
