import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_obb_detector import decode,support_segment,ObbPerception
from arena_oriented import transform
from arena_support import VisualSupports,height,landing_height
from arena_vision import Box,cap_landing


def test_obb_decode_keeps_compound_parts_separate_and_does_not_use_cues_as_damage():
    profile=dict(classes=[dict(kind='player'),dict(kind='hazard',shape='BoxCollider',motion_kind='trap'),
                          dict(kind='hazard',shape='SphereCollider',motion_kind='trap'),dict(kind='cue')])
    role=((172,210),(188,210),(188,250),(172,250))
    wire=transform(((300,150),(310,150),(310,250),(300,250)),.5,(305,200))
    sphere=transform(((290,185),(320,185),(320,215),(290,215)),.7,(305,200))
    player,hazards,supports,cues=decode([role,wire,sphere,wire],[0,1,2,3],[.9]*4,profile)
    assert player.center==(180,230)and len(hazards)==2 and len(cues)==1 and supports==[]
    assert hazards[0].quad==wire
    assert hazards[1].box.w==pytest.approx(30)and hazards[1].box.h==pytest.approx(30)


def test_sloped_support_decodes_physical_centerline_without_supervision_thickness():
    q=np.array([[0,248],[200,148],[202,152],[2,252]],float)
    a,b=support_segment(q)
    assert a==pytest.approx((1,250))and b==pytest.approx((201,150))


def test_visible_support_translation_ignores_a_cropped_endpoint():
    tracker=VisualSupports();player=Box(172,210,16,40)
    for i in range(6):
        stamp=i*.04
        state=tracker.observe([dict(kind='platform',a=(0,260),b=(500-400*stamp,260),confidence=.9)],player,stamp)
    s=state['segments'][0]
    assert s['vx']==pytest.approx(-400)and s['vy']==0
    assert state['terrain']['speed']==pytest.approx(400)
    assert state['terrain']['y']+7==260 and state['terrain']['at_player']


def test_gaps_are_not_filled_by_an_enclosing_rectangle_and_float_motion_changes_landing():
    tracker=VisualSupports();player=Box(172,210,16,40)
    segments=[dict(kind='platform',a=(0,260),b=(230,260),confidence=.9),
              dict(kind='platform',a=(330,260),b=(640,260),confidence=.9)]
    terrain=tracker.observe(segments,player,0)['terrain']
    assert terrain['edge']==230 and terrain['landing']==330
    assert not next(s[2]for s in terrain['samples']if s[0]==280)
    moving=dict(kind='floating_platform',a=(250,260),b=(350,260),vx=-100,vy=-10)
    assert height(moving,180,0)is None
    assert landing_height(dict(segments=[moving]),180,1,100)==250


def test_obb_state_estimator_uses_neural_supports_without_color_or_native_state(monkeypatch):
    class Detector:
        last_ms=1
        def detect(self,rgb):
            return Box(172,210,16,40),[],[dict(kind='rope',a=(0,260),b=(640,260),confidence=.9)],[]
    perception=ObbPerception(Detector())
    monkeypatch.setattr(perception.ground,'observe',lambda *a:pytest.fail('color support entered OBB path'))
    import arena_vision
    monkeypatch.setattr(arena_vision,'arrow_score',lambda *a:pytest.fail('UI heuristic entered OBB path'))
    result=perception.observe(np.zeros((360,640,4),np.uint8),0)
    assert result['phase']=='rope_above'and result['rope']==260 and result['terrain']is None
    assert result['detector']=='standard_yolo26n_obb'


def test_future_landing_uses_prediction_horizon_and_advances_moving_surfaces_once():
    from arena_vision import player_future,advance_player
    from arena_support import describe_terrain
    import arena_motion as motion
    segment=dict(id=1,kind='floating_platform',a=(0,260),b=(640,260),vx=-100,vy=-10)
    terrain=describe_terrain([segment],segment,180)
    obs=dict(time=1,player=Box(172,100,16,40),phase='jump1_falling',motion=dict(name='jump1',started=0),
             terrain=terrain,rope=None,scale_px=40,stand_w=16,stand_h=40,jumps=1,vy=0)
    # The action is already one second old; surface extrapolation uses only
    # the next 0.2 s, not elapsed action time + 0.2 s.
    result=cap_landing(obs,Box(172,300,16,40),1.2,'jump1',forecast_seconds=.2)
    assert result.center[1]==pytest.approx(228)
    grounded=dict(obs,player=Box(172,210,16,40),phase='ground',motion=None,jumps=0)
    predicted=advance_player(grounded,.2)
    assert predicted['player'].center[1]==pytest.approx(228)
    assert predicted['terrain']['y']+7==pytest.approx(258)
    assert predicted['terrain']['segments'][0]['a'][0]==pytest.approx(-20)


def test_neural_platform_at_same_height_across_gap_does_not_report_character_as_grounded():
    class Detector:
        last_ms=1
        def detect(self,rgb):
            return Box(172,210,16,40),[],[dict(kind='platform',a=(230,260),b=(640,260),confidence=.9)],[]
    perception=ObbPerception(Detector())
    result=perception.observe(np.zeros((360,640,4),np.uint8),0)
    assert result['terrain']['at_player']is False
    assert result['phase']=='air_falling'


def test_reusing_loaded_model_resets_role_association_between_independent_episodes():
    class Detector:
        player_x=2.
        def reset_tracking(self):self.player_x=180.
    detector=Detector();ObbPerception(detector)
    assert detector.player_x==180.


def test_observed_rush_speed_is_shared_with_a_later_ready_enemy_using_pixels_only():
    from arena_vision import Detection
    class Detector:
        last_ms=1
        tick=0
        def detect(self,rgb):
            t=self.tick*.04;self.tick+=1
            phase='rush'if t<.2 else'ready'
            box=Box(600-1200*t-15,185,30,30)if phase=='rush'else Box(585,105,30,30)
            return Box(172,210,16,40),[Detection(box,'eye_enemy',.99,phase=='rush',phase=='ready',phase)],\
                [dict(kind='rope',a=(0,260),b=(640,260),confidence=.99)],[]
    actor=ObbPerception(Detector())
    for i in range(6):obs=actor.observe(np.zeros((360,640,3),np.uint8),i*.04)
    ready=next(t for t in obs['tracks']if t.attack_phase=='ready')
    assert obs['observed_rush_velocity']==pytest.approx(-1200)
    assert ready.future(.4).center[0]==pytest.approx(480)


def test_rush_fit_rejects_static_false_phase_and_ignores_own_capsule_horizontal_offsets():
    from arena_vision import Tracker,Detection
    tracker=Tracker(adaptive=True,adaptive_rush_speed=True)
    for i in range(4):
        t=i*.04
        rows=tracker.update([Detection(Box(585-1200*t,185,30,30),'eye_enemy',.99,True,False,'rush')],t,(180+150*t,260))
    assert rows[0].rush_fit_velocity==pytest.approx(-1200)
    assert rows[0].future(.2).center[0]==pytest.approx(600-1200*.12-1200*.2)
    static=Tracker(adaptive=True,adaptive_rush_speed=True)
    for i in range(4):rows=static.update([Detection(Box(585,185,30,30),'eye_enemy',.99,True,False,'rush')],i*.04,(180,260))
    assert rows[0].rush_fit_velocity is None


def test_debug_overlay_draws_float_neural_supports_without_rounding_physics_measurements():
    from arena_vision import overlay
    class Detector:
        last_ms=1
        def detect(self,rgb):
            return Box(172,210,16,40),[],[dict(kind='platform',a=(0,260.25),b=(640,260.25),confidence=.99)],[]
    pixels=np.zeros((360,640,3),np.uint8);obs=ObbPerception(Detector()).observe(pixels,0)
    image=overlay(pixels,obs)
    assert image.shape==(360,640,3)and obs['terrain']['samples'][50][1]==253.25
