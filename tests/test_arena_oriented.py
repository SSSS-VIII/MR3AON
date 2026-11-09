import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Detection,Tracker,Track
from arena_oriented import bounds,transform,touching_capsule,swept_capsules


def observed(stamp,shape='BoxCollider'):
    center=(400-300*stamp,200+50*stamp)
    base=((390,160),(410,160),(410,240),(390,240))
    quad=transform(base,1.4+1.5*stamp,center)
    return Detection(Box(*bounds(quad)),'trap',.95,resource='blade',collider_shape=shape,quad=quad)


def test_rotation_crosses_canonical_axis_boundary_without_losing_angular_velocity():
    tracker=Tracker(adaptive=True)
    for t in np.arange(0,.201,.04):tracks=tracker.update([observed(float(t))],float(t),(180,260))
    track=tracks[0]
    assert track.angular_velocity==pytest.approx(1.5,abs=1e-6)
    expected=observed(.4).quad
    actual=track.future_quad(.2)
    assert np.max(abs(np.asarray(actual)-expected))<1e-5
    assert track.future(.2).center==pytest.approx(np.asarray(expected).mean(0))


def test_occluded_rotated_quad_advances_with_camera_reference_and_matches_its_box():
    tracker=Tracker(adaptive=True)
    for t in(0,.04,.08):tracker.update([observed(t)],t,(180,260))
    predicted=tracker.update([],.12,(185,267))[0]
    assert Box(*bounds(predicted.quad)).center==pytest.approx(predicted.box.center)
    assert np.asarray(predicted.quad).mean(0)==pytest.approx(np.asarray(observed(.12).quad).mean(0)+[5,7])


def test_compound_sphere_is_not_associated_to_a_wire_box_at_the_same_center():
    tracker=Tracker();tracker.update([observed(0)],0,(180,260))
    tracks=tracker.update([observed(.04,'SphereCollider')],.04,(180,260))
    assert len(tracks)==2


def test_oriented_capsule_check_rejects_empty_enclosing_box_corners():
    q=transform(((295,140),(305,140),(305,260),(295,260)),np.pi/4,(300,200))
    assert not touching_capsule(Box(335,235,10,10),q)
    assert touching_capsule(Box(295,195,10,10),q)
    axis=((290,190),(310,190),(310,210),(290,210))
    assert not touching_capsule(Box(309,209,10,10),axis)
    assert touching_capsule(Box(309,209,10,10),axis,margin=1)


def test_swept_oriented_collision_catches_crossings_without_filling_round_corners():
    q=np.array([[[295,140],[305,140],[305,260],[295,260]]],float)
    before=np.array([[250,200,10,10],[250,300,10,10]],float)
    after=np.array([[350,200,10,10],[350,300,10,10]],float)
    assert swept_capsules(before,after,q,q).tolist()==[[True],[False]]
    corner=np.array([[314,214,10,10]],float)
    square=np.array([[[290,190],[310,190],[310,210],[290,210]]],float)
    assert not swept_capsules(corner,corner,square,square)[0,0]
    assert swept_capsules(corner,corner,square,square,1,1)[0,0]


def test_actual_policy_and_search_use_observed_quad_instead_of_empty_aabb_corner():
    from dataclasses import replace
    from arena_policy import VisualAvoider
    from arena_mpc import MpcAvoider
    q=transform(((295,140),(305,140),(305,260),(295,260)),np.pi/4,(300,200))
    track=Track(1,Box(*bounds(q)),'trap',.99,0,observations=4,quad=q,collider_shape='BoxCollider')
    obs=dict(player=Box(332,221.5,16,37),time=0,phase='rope_above',rope=270,terrain=None,
             jumps=0,motion=None,scale_px=40,stand_w=16,stand_h=37,tracks=[track])
    assert VisualAvoider()._risk(obs,'none')[0]==0
    assert VisualAvoider()._risk(dict(obs,tracks=[replace(track,quad=None,collider_shape=None)]),'none')[0]>0
    other=replace(track,id=2,quad=transform(q,0,(550,100)),box=Box(*bounds(transform(q,0,(550,100)))),angular_velocity=1.)
    assert MpcAvoider().choose(dict(obs,tracks=[track,other]))==(None,'mpc_wait')
