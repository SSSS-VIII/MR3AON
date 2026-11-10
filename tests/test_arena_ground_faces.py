"""Ground entrances constrain rope routes without inventing walls at seams."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_support import leading_ground_faces
from arena_policy import VisualAvoider
from arena_mpc import MpcAvoider
from arena_vision import Box


def surface(identity,a,b,kind='platform',confidence=.95):
    return dict(id=identity,kind=kind,a=(a,260),b=(b,260),vx=-500,vy=0,stamp=0,confidence=confidence)


def observation(segments,below=True,stamp=0):
    return dict(player=Box(172,270 if below else 211,16,37),phase='rope_below'if below else'rope_above',
        rope=260.,terrain=None,jumps=0,motion=None,time=stamp,vy=0,tracks=[],scale_px=39.5,
        stand_w=14.2,stand_h=37.,visible_supports=segments)


def test_same_height_ground_seams_and_floating_surfaces_do_not_become_vertical_walls():
    joined=[surface(1,0,300),surface(2,300,640),surface(3,200,400,'floating_platform')]
    assert leading_ground_faces(joined,0)==[]
    gap=[surface(1,0,300),surface(2,320,640)]
    assert [f['x']for f in leading_ground_faces(gap,0)]==[320]
    assert leading_ground_faces([surface(1,300,640,confidence=.4)],0)==[]


def test_camera_and_pixel_age_translation_are_applied_once_before_forecasting():
    s=surface(1,400,640);s['stamp']=10;s['vy']=-20
    obs=observation([s],stamp=10.1)
    wall=VisualAvoider()._objects(obs)[0]
    assert wall.box.x==pytest.approx(350)
    assert wall.box.y==pytest.approx(264)
    assert wall.future(.2).x==pytest.approx(250)
    assert wall.future(.2).y==pytest.approx(260)


def test_search_returns_above_rope_before_ground_entry_but_walks_normally_on_top():
    segments=[surface(1,275,640)]
    below=observation(segments)
    assert VisualAvoider()._risk(below,'none')[0]>0
    # Original climbDistance probes ahead of the hurt capsule. A short block
    # during the flip is recoverable and cheaper than remaining underneath.
    assert VisualAvoider()._risk(below,'flip')[0]<VisualAvoider()._risk(below,'none')[0]
    assert MpcAvoider().choose(below)==('jump','mpc_rope_up')
    above=observation(segments,False)
    assert VisualAvoider()._risk(above,'none')[0]==0
    assert MpcAvoider().choose(above)==(None,'mpc_wait')


def test_ground_geometry_does_not_pollute_detector_tracks_or_require_enemy_detections():
    obs=observation([surface(1,275,640)])
    assert MpcAvoider().uses_search(obs)
    assert all(t.kind=='terrain_wall'and t.id<0 for t in VisualAvoider()._objects(obs))
    assert obs['tracks']==[] and obs['visible_supports'][0]['a']==(275,260)


def test_repeated_weak_platform_is_a_possible_wall_without_turning_one_weak_frame_solid():
    weak=surface(1,300,640,confidence=.4)
    assert leading_ground_faces([weak],0)==[]
    weak['observations']=3
    walls=VisualAvoider()._objects(observation([weak]))
    assert len(walls)==1 and walls[0].kind=='terrain_wall'
    assert walls[0].confidence==.4
