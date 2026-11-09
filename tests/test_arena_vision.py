"""Geometry/motion regressions from real arena experiments, no client assets."""
from pathlib import Path
import sys
import pytest

cv2=pytest.importorskip('cv2')
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Detection,Track,Tracker,Perception
from arena_policy import Avoider
from arena_terrain import arrow_score
from arena_terrain import GroundEdges
from arena_visual_runner import evaluation_status


def hazard(identity,x,y,*,arming=False,active=True):
    track=Track(identity,Box(x,y,30,24),'eye_enemy',.93,0)
    track.vx=-850;track.observations=5;track.active=active;track.arming=arming
    return track


def observation(phase='rope_above',tracks=(),stamp=1):
    return dict(player=Box(170,210 if phase=='rope_above' else 270,20,40),
                time=stamp,phase=phase,rope=260,jumps=0,tracks=list(tracks))


def test_speed_regression_cancels_foreground_camera_translation():
    tracker=Tracker()
    for i in range(9):
        t=i*.04
        result=tracker.update([Detection(Box(600-800*t,100+70*t,30,24),'eye_enemy',.9)],
                              t,(180,260+70*t))
    assert len(result)==1 and result[0].observations==9
    assert result[0].vx==pytest.approx(-800,abs=1)
    assert result[0].vy==pytest.approx(0,abs=.01)


def test_track_identity_survives_attack_colour_and_acceleration():
    tracker=Tracker()
    identities=[]
    for i,x in enumerate([500,500,490,465,425,385]):
        tracks=tracker.update([Detection(Box(x,210,30,24),'eye_enemy',.93,i>=3,i==2)],
                              i*.04,(180,260))
        identities.append(tracks[0].id)
    assert len(set(identities))==1
    assert tracks[0].vx < -650
    assert tracks[0].active


def test_above_rope_uses_down_and_below_uses_jump_to_change_sides():
    assert Avoider().choose(observation(tracks=[hazard(1,390,216)]))[0]=='down'
    assert Avoider().choose(observation('rope_below',[hazard(1,390,278)]))[0]=='jump'


def test_same_column_on_both_sides_requires_jump_even_with_a_new_track():
    upper=hazard(1,390,216,arming=True,active=False)
    lower=hazard(2,390,278,arming=True,active=False)
    lower.vx=0;lower.observations=1
    action,reason=Avoider().choose(observation(tracks=[upper,lower]))
    assert action is None  # Wait for the actual dash before timing a jump.
    upper.active=True
    assert Avoider().choose(observation(tracks=[upper,lower]))[0]=='jump'


def test_under_rope_escape_returns_above_then_jumps_without_full_flip_cooldown():
    policy=Avoider()
    threats=[hazard(1,500,216,arming=True),hazard(2,500,278,arming=True)]
    action,reason=policy.choose(observation('rope_below',threats))
    assert action=='jump' and reason.startswith('under_rope_escape')
    action,reason=policy.choose(observation('rope_above',threats,stamp=1.31))
    assert action=='jump' and reason=='complete_under_rope_escape'


def picture(red_enemy=False,head_y=215):
    image=np.full((360,640,3),(70,110,190),np.uint8)
    cv2.line(image,(0,260),(639,260),(0,0,0),4)
    cv2.fillPoly(image,[np.array([(89,298),(101,298),(101,313),(110,313),
                                  (95,330),(80,313),(89,313)],np.int32)],(255,255,255))
    cv2.line(image,(0,217),(181,head_y+9),(240,15,15),5)
    cv2.circle(image,(193,head_y),11,(0,0,0),-1)
    cv2.rectangle(image,(174,head_y+10),(185,head_y+30),(0,0,0),-1)
    cv2.ellipse(image,(430,222),(17,12),0,0,360,(180,25,30) if red_enemy else (0,0,0),-1)
    cv2.circle(image,(430,219),4,(240,160,20),-1)
    # Coin ring has the same golden hue but lacks a dark enemy body.
    cv2.circle(image,(530,230),6,(220,170,70),2)
    return image


def test_pixels_separate_player_rope_enemy_and_coin():
    result=Perception().observe(picture(),1)
    assert result['phase']=='rope_above'
    assert result['rope']==pytest.approx(260,abs=2)
    assert result['player'].center[0]==pytest.approx(179,abs=5)
    enemies=[d for d in result['detections'] if d.kind=='eye_enemy']
    assert len(enemies)==1
    assert enemies[0].box.center[0]==pytest.approx(430,abs=3)


def test_red_attack_preserves_visual_detection_and_arming_state():
    perception=Perception()
    first=perception.observe(picture(),1)
    identity=next(t.id for t in first['tracks'] if t.kind=='eye_enemy')
    second=perception.observe(picture(red_enemy=True),1.04)
    enemy=next(t for t in second['tracks'] if t.kind=='eye_enemy')
    assert enemy.id==identity and enemy.arming


def test_head_moves_up_with_character_rather_than_following_scarf_tail():
    perception=Perception()
    first=perception.observe(picture(),1)
    second=perception.observe(picture(head_y=195),1.04)
    assert first['player'].center[1]-second['player'].center[1]==pytest.approx(20,abs=5)


def test_damage_overrides_board_completion_even_with_stale_minimum_health():
    initial={'health':5000}
    assert evaluation_status(initial,dict(health=4487,minHealth=5000,damage=0,stageIndex=3),3)=='damage'
    assert evaluation_status(initial,dict(health=5000,minHealth=4880,damage=120,stageIndex=3),3)=='damage'
    assert evaluation_status(initial,dict(health=5000,minHealth=5000,damage=0,stageIndex=3),3)=='passed'


def test_temporarily_occluded_trap_is_predicted_and_reassociated():
    tracker=Tracker()
    for i in range(5):
        tracks=tracker.update([Detection(Box(500-500*i*.04,210,30,24),'eye_enemy',.93)],i*.04,(180,260))
    identity=tracks[0].id
    predicted=tracker.update([],.28,(180,240))
    assert len(predicted)==1 and predicted[0].id==identity
    assert predicted[0].box.x==pytest.approx(360,abs=1)
    assert predicted[0].box.y==pytest.approx(190,abs=1)
    visible=tracker.update([Detection(Box(340,190,30,24),'eye_enemy',.93)],.32,(180,240))
    assert len(visible)==1 and visible[0].id==identity
    assert tracker.update([],.60,(180,240))==[]


def test_curved_motion_fits_acceleration_and_predicts_short_horizon():
    tracker=Tracker()
    for i in range(14):
        t=i*.04
        tracks=tracker.update([Detection(Box(600-500*t,120+70*t+200*t*t,30,24),'eye_enemy',.93)],
                              t,(180,260))
    track=tracks[0]
    assert track.curve_count>=3 and track.ay==pytest.approx(400,abs=1)
    assert track.future(.1).y==pytest.approx(120+70*(t+.1)+200*(t+.1)**2,abs=.1)


def test_dimmed_arrow_does_not_turn_rope_into_ground():
    image=picture()
    region=image[290:339,73:118]
    white=region.min(2)>205
    region[white]=(125,150,185)
    assert arrow_score(image,95)>.5
    assert Perception().observe(image,1)['phase']=='rope_above'


def test_wide_spider_eyes_are_not_rejected_as_coin_rims():
    image=picture()
    cv2.rectangle(image,(400,190),(460,250),(70,110,190),-1)
    cv2.circle(image,(430,222),12,(0,0,0),-1)
    cv2.line(image,(430,60),(430,210),(0,0,0),2)
    cv2.ellipse(image,(430,222),(6,3),0,0,360,(245,150,15),-1)
    detections=Perception().observe(image,1)['detections']
    assert any(d.kind=='spider' for d in detections)


def test_planner_rejects_flip_that_runs_into_next_lower_trap():
    action,_=Avoider().choose(observation(tracks=[hazard(1,350,216),hazard(2,420,278)]))
    assert action=='jump'


def test_periodic_motion_prediction_survives_advancing_cached_track():
    tracker=Tracker()
    for i in range(28):
        t=i*.025
        tracks=tracker.update([Detection(Box(620-650*t,180+41*np.sin(3*t+1),30,24),'eye_enemy',.93)],
                              t,(180,260))
    track=tracks[0]
    assert track.sine_count>=2 and track.sine_frequency==3
    expected=180+41*np.sin(3*(t+.4)+1)
    assert track.future(.4).y==pytest.approx(expected,abs=.1)
    assert track.at(.1).future(.3).y==pytest.approx(expected,abs=.1)


def test_scaled_enemy_eye_produces_larger_danger_box():
    image=picture()
    cv2.rectangle(image,(390,185),(475,255),(70,110,190),-1)
    cv2.ellipse(image,(430,222),(34,24),0,0,360,(0,0,0),-1)
    cv2.circle(image,(430,219),8,(240,160,20),-1)
    result=Perception().observe(image,1)
    enemies=[d for d in result['detections']if d.kind=='eye_enemy']
    assert len(enemies)==1 and enemies[0].box.w>45 and enemies[0].box.h>35


def test_white_sclera_and_red_pupil_are_a_full_size_pinball():
    image=picture()
    cv2.rectangle(image,(390,185),(475,255),(70,110,190),-1)
    cv2.circle(image,(430,222),23,(0,0,0),-1)
    cv2.circle(image,(430,222),12,(245,235,235),-1)
    cv2.circle(image,(434,224),4,(230,20,20),-1)
    enemies=Perception().observe(image,1)['detections']
    ball=next(d for d in enemies if d.kind=='pinball')
    assert ball.box.w>40 and ball.box.h>40


def test_foreground_gap_and_scroll_speed_are_measured_from_pixels():
    edges=GroundEdges()
    for i in range(4):
        image=np.full((360,640,3),(70,110,190),np.uint8)
        image[250:275,:420-i*20]=(20,65,90)
        image[250:275,550-i*20:]=(20,65,90)
        result=edges.observe(image,Box(170,210,20,40),i*.04)
    assert result['edge']==pytest.approx(360,abs=8)
    assert result['landing']==pytest.approx(490,abs=8)
    assert result['speed']==pytest.approx(500,abs=50)


def test_two_small_spider_eyes_join_without_losing_dark_background_detection():
    image=picture()
    image[55:105,490:560]=(10,12,18)
    cv2.rectangle(image,(519,69),(522,74),(245,150,15),-1)
    cv2.rectangle(image,(526,69),(529,74),(245,150,15),-1)
    enemies=Perception().observe(image,1)['detections']
    assert any(d.confidence>.7 and 510<d.box.center[0]<540 and d.box.center[1]<100 for d in enemies)


@pytest.mark.parametrize('stay,jump,expected',[(0,100,None),(100,0,'jump'),(400,200,None)])
def test_escape_followup_rechecks_new_hazards_before_second_input(stay,jump,expected):
    class ChangedScene(Avoider):
        def _risk(self,obs,action):
            return (jump if action=='jump'else stay),10,{}
    policy=ChangedScene();policy.followup_until=2.;policy.last_action=1.
    action,reason=policy.choose(observation('rope_above',[],stamp=1.35))
    assert action==expected
    assert reason==('complete_under_rope_escape'if expected else'clear')
    assert policy.followup_until<1.3
