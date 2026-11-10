"""PinballBase uses its own LevelBlock height at its own X, not the role's."""
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_object_support import object_support
from arena_vision import Box,Detection,Track,Tracker
from arena_object_motion import bounce_state


def surface(a,b,kind='platform'):
    return dict(a=a,b=b,kind=kind,confidence=.95,vx=-400.,vy=0.)


def test_object_floor_uses_its_position_and_excludes_floating_platforms():
    segments=[surface((0,260),(240,260)),surface((300,220),(640,100)),
              surface((300,170),(640,170),'floating_platform')]
    detection=Detection(Box(410,100,20,20),'pinball',.9)
    support=object_support(segments,detection)
    assert support['y']==pytest.approx(220-120*120/340)
    tracker=Tracker(adaptive=True)
    tracks=tracker.update([detection],0,(0,0),lambda d:object_support(segments,d))
    assert tracks[0].floor_y==pytest.approx(support['y']-10)
    assert tracks[0].floor_y!=250
    assert object_support(segments,Detection(Box(255,100,20,20),'pinball',.9))is None


def test_moving_slope_rebound_and_clock_retiming_match_same_events():
    ball=Track(1,Box(300,208,20,20),'pinball',.95,0,vx=-500.,vy=180.,ballistic=True,
               gravity_up=320.,gravity_down=320.,rebound_speed=280.,floor_y=240.,floor_vy=20.)
    direct=ball.future(.3);split=ball.at(.1).future(.2)
    assert direct.center==pytest.approx(split.center)
    static=ball.future(.2);ball.floor_vy=0
    assert static.center[1]!=pytest.approx(ball.future(.2).center[1])


def test_unknown_or_finished_visible_floor_does_not_create_a_rebound():
    ball=Track(1,Box(300,200,20,20),'pinball',.95,0,vx=-500.,vy=100.,ballistic=True,
               gravity_up=320.,gravity_down=320.,rebound_speed=280.,floor_y=None)
    assert ball.future(.3).center[1]==pytest.approx(210+100*.3+.5*320*.3**2)
    ball.floor_y=250.;ball.floor_segment=dict(a=(300,260),b=(640,260),vx=0.,vy=0.)
    assert ball.at(.1).floor_y is None
    assert ball.at(.1).future(.2).center==pytest.approx(ball.future(.3).center)
