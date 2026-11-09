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
