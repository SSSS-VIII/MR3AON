import json
import math
from pathlib import Path
import numpy as np
import pytest
from arena_vision import Box,Track
from arena_policy import VisualAvoider,touching
from arena_oriented import touching_capsule,transform
from arena_reactive_sweep import swept_pair,rectangle_quad,player_smooth_padding
SweptAvoider=VisualAvoider

# Frozen old endpoint checker is a test-only reference.
from arena_policy import Avoider
import importlib.util
ROOT=Path(__file__).resolve().parents[1]
ref=ROOT/'tests/fixtures/arena-policy-before-sweep.py'
spec=importlib.util.spec_from_file_location('policy_before_sweep',ref)
legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
EndpointAvoider=legacy.VisualAvoider




def restore(row):
    obs=dict(row)
    for key in('player','silhouette'):
        if isinstance(obs.get(key),dict):obs[key]=Box(**obs[key])
    obs['tracks']=[Track(**dict(track,box=Box(**track['box'])))for track in row['tracks']]
    return obs


@pytest.fixture(scope='module')
def snapshot():
    return restore(json.loads((ROOT/'tests/fixtures/arena-reactive-paw-747.json').read_text()))


@pytest.mark.parametrize('shape',['box','ellipse'])
def test_opposing_fast_crossing_with_safe_endpoints(shape):
    a,b=Box(-10,-1,2,2),Box(10,-1,2,2)
    c,d=Box(10,-1,2,2),Box(-10,-1,2,2)
    assert not touching(a,c,0,shape=shape)and not touching(b,d,0,shape=shape)
    assert swept_pair(a,b,c,d,shape=shape,margin=0)


@pytest.mark.parametrize('shape',['box','ellipse'])
def test_parallel_nearby_pass_retains_a_real_gap(shape):
    assert not swept_pair(Box(-10,-1,2,2),Box(10,-1,2,2),
                          Box(10,2.1,2,2),Box(-10,2.1,2,2),shape=shape,margin=0)


@pytest.mark.parametrize('shape',['box','ellipse'])
def test_horizontal_capsule_body_core_is_retained(shape):
    player=Box(-20,-2,40,4);target=Box(14,-1,2,2)
    assert swept_pair(player,player,target,target,shape=shape,margin=0)
    far=Box(22.1,-1,2,2)
    assert not swept_pair(player,player,far,far,shape=shape,margin=0)


def test_horizontal_vertical_pose_union_keeps_diagonal_corner_support():
    horizontal=Box(-20,-2,40,4);vertical=Box(-2,-20,4,40)
    corner=Box(17,17,.2,.2)
    assert swept_pair(horizontal,vertical,corner,corner,shape='box',margin=0)
    far=Box(21,21,.2,.2)
    assert not swept_pair(horizontal,vertical,far,far,shape='box',margin=0)


def test_rotating_tip_arc_outside_endpoint_hull_is_covered():
    old=rectangle_quad(Box(-10,-.25,20,.5));new=np.array(transform(old,math.pi/2,(0,0)))
    player=Box(6.9,6.9,.3,.3);hazard=Box(-10,-10,20,20)
    assert not touching_capsule(player,old)and not touching_capsule(player,new)
    assert not swept_pair(player,player,hazard,hazard,shape='box',old_quad=old,new_quad=new,margin=0)
    assert swept_pair(player,player,hazard,hazard,shape='box',old_quad=old,new_quad=new,angle=math.pi/2,margin=0)


def test_full_rotation_with_identical_endpoints_still_has_arc_envelope():
    q=rectangle_quad(Box(-10,-.25,20,.5));body=Box(-.2,7.8,.4,.4);hazard=Box(-10,-1,20,2)
    assert swept_pair(body,body,hazard,hazard,shape='box',old_quad=q,new_quad=q,angle=2*math.pi,margin=0)


def test_vertical_arc_padding_covers_midflight_but_not_a_distant_target():
    a,b=Box(-5,-1,2,2),Box(5,-1,2,2);target=Box(-1,4,2,2)
    assert not swept_pair(a,b,target,target,margin=0)
    assert swept_pair(a,b,target,target,curve_padding=(0,5),margin=0)
    far=Box(-1,10,2,2)
    assert not swept_pair(a,b,far,far,curve_padding=(0,5),margin=0)


def test_first_interval_includes_current_contact(snapshot):
    obs=dict(snapshot);p=obs['player']
    obs['tracks']=[Track(900,Box(p.x,p.y,2,2),'trap',1,obs['time'],
                         observations=4,vx=20000,collider_shape='SphereCollider')]
    # Put the tiny sphere on the central capsule spine, not in an empty AABB corner.
    obs['tracks'][0].box=Box(p.center[0]-1,p.center[1]-1,2,2)
    assert EndpointAvoider()._risk(obs,'none')[0]==0
    assert SweptAvoider()._risk(obs,'none')[2][900][0]==.04


def test_terrain_wall_endpoint_duration_cost_is_unchanged(snapshot):
    obs=dict(snapshot);p=obs['player']
    obs['tracks']=[Track(901,Box(p.center[0]+40,p.y,1,1000),'terrain_wall',1,obs['time'],
                         observations=4,vx=-120,collider_shape='BoxCollider')]
    for action in('none','jump','slide'):
        old=EndpointAvoider()._risk(obs,action);new=SweptAvoider()._risk(obs,action)
        assert old[:2]==new[:2]


def test_flat_ground_has_no_freefall_padding(snapshot):
    for action in('none','slide','jump'):
        after=VisualAvoider()._path(snapshot,action,.04)
        assert np.array_equal(player_smooth_padding(snapshot,action,0,.04,after),[0.,0.])
    airborne=dict(snapshot,phase='jump1_rising',motion=None,jumps=1,terrain=None)
    assert player_smooth_padding(airborne,'none',0,.04,airborne['player'])[1]>0


def test_frozen_frame747_slide_miss_is_recovered_without_changing_40ms_steps(snapshot):
    old=EndpointAvoider()._risk(snapshot,'slide');new=SweptAvoider()._risk(snapshot,'slide')
    assert old[0]==0 and not old[2]
    assert new[0]>0 and 52 in new[2]
    assert new[2][52][0]in(.28,.32)
    assert all(abs(t/.04-round(t/.04))<1e-8 for t,_ in new[2].values())
    assert SweptAvoider()._risk(snapshot,'jump')[0]==0
