"""Native numeric trace and independent projectile/crop geometry regressions."""
import sys,json,math
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_arrow_motion import ArrowTrack,velocity_prior,restore_tail
from arena_vision import Box,Detection,Tracker,serializable
from arena_projection import SCALE
from arena_mpc import MpcAvoider
from arena_oriented import bounds
from arena_yolo_obb_data import visible_quad

L=2.2*SCALE;W=.07*SCALE;SCENE=-1800+30*SCALE


def physical_quad(root,vy):
    direction=np.array([30*SCALE,-vy]);direction/=np.linalg.norm(direction)
    normal=np.array([-direction[1],direction[0]])*W/2
    head=np.asarray(root);tail=head+direction*L
    return tuple(tuple(map(float,p))for p in(head-normal,tail-normal,tail+normal,head+normal))


def trajectory(acceleration,stamps):
    tracker=Tracker(adaptive=True)
    for t in stamps:
        quad=physical_quad((520-1800*t,90+100*t+.5*acceleration*t*t),100+acceleration*t)
        detection=Detection(Box(*bounds(quad)),'arrow',.95,collider_shape='BoxCollider',quad=quad,scene_velocity_x=SCENE)
        detection.velocity_prior=velocity_prior(detection,SCENE)
        track=tracker.update([detection],t,(0.,0.),None)[0]
    return track


def native_trace():
    return json.loads((Path(__file__).parent/'fixtures/arena_arrow_native_trace.json').read_text())['frames']


def trace_track(frames):
    track=ArrowTrack(1,Box(0,0,1,1),'arrow',.95,0.)
    track.adaptive_velocity=True
    for row in frames:
        d=Detection(Box(*bounds(row['quad'])),'arrow',.95,collider_shape='BoxCollider',quad=tuple(map(tuple,row['quad'])),scene_velocity_x=row['floor']['vx'],geometry_restored=True)
        track.update(d,row['t'],tuple(row['reference']),lambda d,row=row:dict(y=row['reference'][1],segment=row['floor']))
    return track


def test_native_collider_shrink_still_recovers_original_movement_root():
    frames=native_trace();track=trace_track(frames)
    row=frames[-1];root=track.root_history[-1][1:]
    actual=np.asarray(row['root_point'])-row['reference']
    assert np.linalg.norm(np.subtract(root,actual))<3.5
    assert max(np.linalg.norm(np.subtract(t[1:],np.asarray(f['root_point'])-f['reference']))for t,f in zip(track.root_history,frames[-8:]))<3.5


def test_native_flight_to_ground_is_a_stopping_shortening_arrow_not_an_unbounded_parabola():
    frames=native_trace();track=trace_track(frames[:4]);target=frames[5]
    future=track.future(target['t']-frames[3]['t']);quad=np.asarray(target['quad']);quad[:,1]-=target['reference'][1]-frames[3]['reference'][1]
    assert all(future.x-4<=x<=future.x+future.w+4 and future.y-4<=y<=future.y+future.h+4 for x,y in quad)
    assert any(state.grounded for state in track.at(.2).models)


def test_native_shortened_arrow_retains_stop_hypothesis_before_long_fit_settles():
    frames=native_trace();track=trace_track(frames[:7]);target=frames[10]
    forecast=track.future(target['t']-frames[6]['t']);quad=np.asarray(target['quad']);quad[:,1]-=target['reference'][1]-frames[6]['reference'][1]
    assert any(m.grounded for m in track.models)
    assert all(forecast.x-5<=x<=forecast.x+forecast.w+5 and forecast.y-5<=y<=forecast.y+forecast.h+5 for x,y in quad)


def test_arrow_impact_plane_memory_expires_without_new_material_observation():
    frames=native_trace();track=trace_track(frames[:5]);observed=track.last_floor_seen
    for row in frames[5:8]:
        d=Detection(Box(*bounds(row['quad'])),'arrow',.95,collider_shape='BoxCollider',quad=tuple(map(tuple,row['quad'])),geometry_restored=True)
        track.update(d,row['t'],tuple(row['reference']),lambda d:None)
        assert track.last_floor_seen==observed
        assert (track.floor_segment is not None)==(row['t']-observed<=.12)


def test_straight_root_is_not_forced_to_calibration_gravity():
    track=trajectory(0.,[0.,.04,.08,.12,.16,.2])
    assert track.models and all(m.ay==0 for m in track.models)
    assert all(m.y==pytest.approx(110,abs=.001)for m in track.models)


def test_short_ambiguous_arc_retains_both_positions_in_collision_envelope():
    gravity=25*3.5*SCALE;track=trajectory(gravity,[0.,.02,.04])
    assert len(track.models)==2 and track.quad is None
    actual=physical_quad((520-1800*.24,90+100*.24+.5*gravity*.24**2),100+gravity*.24)
    forecast=track.future(.2)
    assert all(forecast.x-1e-5<=x<=forecast.x+forecast.w+1e-5 and forecast.y-1e-5<=y<=forecast.y+forecast.h+1e-5 for x,y in actual)


def test_projection_preserves_hypotheses_without_reinflating_uncertainty():
    track=trajectory(25*3.5*SCALE,[0.,.02,.04]);direct=track.future(.2);split=track.at(.05).future(.15)
    assert split.center==pytest.approx(direct.center,abs=.0001)
    assert (split.w,split.h)==pytest.approx((direct.w,direct.h),abs=.0001)
    # Private memoization must not bloat each frame's JSON or break key encoding.
    assert '_forecast_cache'not in serializable(dict(tracks=[track]))['tracks'][0]


def test_fast_descending_arrow_can_associate_before_three_visual_matches():
    track=trajectory(25*3.5*SCALE,[0.,.05,.1])
    assert track.id==1 and track.observations==3


def test_new_family_still_uses_existing_airborne_search():
    track=trajectory(0.,[0.,.04,.08]);track.box=Box(360,210,60,8)
    obs=dict(time=.08,player=Box(170,150,16,37),phase='jump1_falling',jumps=1,terrain=dict(source='neural_segments'),rope=None,tracks=[track],motion=None)
    assert MpcAvoider().uses_search(obs)


def test_right_crop_reconstructs_tail_only_above_a_real_visible_floor():
    quad=physical_quad((600,120),700);clipped=visible_quad(quad)
    detection=Detection(Box(*bounds(clipped)),'arrow',.9,collider_shape='BoxCollider',quad=tuple(map(tuple,clipped)))
    floor=dict(kind='platform',id=1,a=(0,280),b=(640,280),vx=-700,vy=0,confidence=.95,left_clipped=True,right_clipped=True)
    restore_tail(detection,[floor])
    assert detection.geometry_restored
    assert max(x for x,y in detection.quad)>640
    track=ArrowTrack(1,detection.box,'arrow',.9,0.)
    track.update(detection,0.,(0.,0.))
    assert track.root_history[-1][1:]==pytest.approx((600,120),abs=2)
    other=Detection(Box(*bounds(clipped)),'arrow',.9,collider_shape='BoxCollider',quad=tuple(map(tuple,clipped)))
    restore_tail(other,[])
    assert not other.geometry_restored
