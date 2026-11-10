"""Source-bound pivot ambiguity, native pose calibration and planner sweeps."""
import sys,math,json
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_mace_motion import MaceTrack
from arena_oriented import transform,bounds
from arena_vision import Box,Detection,Tracker,serializable
from arena_mpc import MpcAvoider,forecast_geometry
from arena_obb_detector import decode

RATIO=1.4/1.9


def quad(t,omega=4.,phase=0.):
    a=phase+omega*t;radius=76*RATIO
    return transform(((-38,-9),(38,-9),(38,9),(-38,9)),a,
        (520-700*t+radius*math.cos(a),200+radius*math.sin(a)))


def trajectory(times,omega=4.,phase=0.,scene=True):
    tracker=Tracker(adaptive=True)
    for t in times:
        q=quad(t,omega,phase);d=Detection(Box(*bounds(q)),'mace',.95,collider_shape='BoxCollider',quad=q,scene_velocity_x=-700. if scene else None,pivot_offset_ratio=RATIO)
        track=tracker.update([d],float(t),(0.,0.))[0]
    return track


@pytest.mark.parametrize('omega',[4.,-4.])
def test_known_eccentric_ratio_recovers_pivot_without_fitting_an_unknown_radius(omega):
    times=np.arange(8)*.03;track=trajectory(times,omega)
    assert track.models and track.quad is None
    target=quad(float(times[-1]+.2),omega);box=track.future(.2)
    assert all(box.x-.001<=x<=box.x+box.w+.001 and box.y-.001<=y<=box.y+box.h+.001 for x,y in target)
    assert min(abs(m.vx+700)for m in track.models)<.001


def test_short_ambiguous_pivots_are_retained_instead_of_guessing_one_axis():
    track=trajectory([0,.021,.042,.063],omega=4.,phase=math.pi/2-.126,scene=False)
    assert len(track.models)==2


def test_native_gold_mace_geometry_predicts_around_the_source_root():
    fixture=json.loads((Path(__file__).parent/'fixtures/arena_mace_native_trace.json').read_text());frames=fixture['frames']
    track=MaceTrack(1,Box(0,0,1,1),'mace',.95,0.)
    for row in frames[:6]:
        q=row['quad'];track.update(Detection(Box(*bounds(q)),'mace',.95,collider_shape='BoxCollider',quad=tuple(map(tuple,q)),pivot_offset_ratio=RATIO),row['t'],tuple(row['reference']))
    assert track.models
    source_root=np.asarray(frames[5]['root_point'])-frames[5]['reference']
    assert min(np.linalg.norm(np.subtract((m.x-m.rx,m.y-m.ry),source_root))for m in track.models)<.001
    target=frames[8];horizon=target['t']-frames[5]['t'];prediction=track.future(horizon)
    q=np.asarray(target['quad']);q[:,1]-=target['reference'][1]-frames[5]['reference'][1]
    # The original angle rate/camera speed vary over this interval. The pose
    # uncertainty must contain the actual whole box, not claim exact speed.
    assert all(prediction.x<=x<=prediction.x+prediction.w and prediction.y<=y<=prediction.y+prediction.h for x,y in q)


def test_projection_preserves_accumulated_parameter_uncertainty_once():
    track=trajectory(np.arange(8)*.03)
    from dataclasses import replace
    track.models=tuple(replace(m,omega_error=.2)for m in track.models)
    direct=track.future(.3);split=track.at(.1).future(.2)
    assert split.center==pytest.approx(direct.center,abs=.001)
    assert (split.w,split.h)==pytest.approx((direct.w,direct.h),abs=.001)
    assert '_forecast_cache'not in serializable(dict(tracks=[track]))['tracks'][0]


def test_cropped_body_cannot_supply_a_fake_shorter_source_pivot():
    track=trajectory(np.arange(8)*.03);assert track.models
    q=((620,180),(640,180),(640,220),(620,220))
    track.update(Detection(Box(*bounds(q)),'mace',.95,collider_shape='BoxCollider',quad=q,pivot_offset_ratio=RATIO),.25,(0.,0.))
    assert not track.models and not track.poses


def test_forecast_zero_contains_the_latest_visible_body_despite_length_jitter():
    track=trajectory(np.arange(8)*.03);q=quad(.24)
    center=np.mean(q,axis=0);q=tuple(tuple(center+1.1*(np.asarray(p)-center))for p in q)
    track.update(Detection(Box(*bounds(q)),'mace',.95,collider_shape='BoxCollider',quad=q,pivot_offset_ratio=RATIO),.24,(0.,0.))
    assert track.models
    box=track.future(0.)
    assert all(box.x-.001<=x<=box.x+box.w+.001 and box.y-.001<=y<=box.y+box.h+.001 for x,y in q)


def test_arc_chord_guard_is_used_by_existing_mpc_boxes():
    track=trajectory(np.arange(8)*.03);times=np.array([0.,.04])
    raw=[track.future(float(t))for t in times]
    boxes,_,oriented,_,_=forecast_geometry([track],times,lambda t,s:t.future(float(s)),.04)
    guard=track.sweep_margin(.04)
    assert guard>0 and not any(oriented)
    assert boxes[:,0,2]==pytest.approx([b.w/2+guard for b in raw])
    obs=dict(time=.21,player=Box(172,150,16,37),phase='jump1_falling',jumps=1,terrain=dict(source='neural_segments'),rope=None,tracks=[track],motion=None)
    assert MpcAvoider().uses_search(obs)


def test_source_pivot_ratio_reaches_the_typed_tracker_through_real_decode():
    profile=dict(classes=[dict(kind='hazard',shape='BoxCollider',motion_kind='mace',pivot_offset_ratio=RATIO)])
    q=quad(0.);_,detections,_,_=decode([q],[0],[.95],profile)
    assert detections[0].pivot_offset_ratio==RATIO
    track=Tracker(adaptive=True).update(detections,0.,(0.,0.))[0]
    assert isinstance(track,MaceTrack)


def test_degenerate_new_quad_disables_the_model_without_reading_a_missing_angle():
    track=trajectory(np.arange(8)*.03)
    q=((300,180),(350,180),(350,180),(300,180))
    track.update(Detection(Box(*bounds(q)),'mace',.95,collider_shape='BoxCollider',quad=q,pivot_offset_ratio=RATIO),.24,(0.,0.))
    assert not track.models and not track.poses
