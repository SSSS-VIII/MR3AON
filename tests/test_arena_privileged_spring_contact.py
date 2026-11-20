"""Original angled spring trigger avoidance, without invented launch physics."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import pending_spring_contact
from arena_privileged_model import PlayerModel,hazard_forecasts,clearance
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-spring-contact.json').read_text())


def test_original_rotated_root_boxes_match_spawn_and_remain_inside_guard():
    o=DATA['observation'];template=o['spawn_templates']['spring'];assert DATA['cases']
    checked=0
    for case in DATA['cases']:
        original=deepcopy(case['entry']);item,reason=pending_spring_contact(case['entry'],template,o)
        assert not reason and case['entry']==original;box=item['colliders'][0]
        for q in case['after']:
            actual=q['item']['colliders'][0]
            for key in ('center','extents'):
                assert np.allclose([box[key][a]for a in('x','y','z')],
                                   [actual[key][a]for a in('x','y','z')],atol=.0002,rtol=0)
            # Check the oriented box, not only a loose world AABB.
            expected=np.array([[p['x'],p['y']]for p in box['quad']]);truth=np.array([[p['x'],p['y']]for p in actual['quad']])
            assert max(min(np.linalg.norm(expected-p,axis=1))for p in truth)<.0002
            checked+=1
    assert checked


def test_uninitialized_nearest_does_not_put_far_springs_at_zero_or_grant_pop():
    o=DATA['observation'];model=PlayerModel(o)
    entries=[e for e in o['pending_items']if e['info']['_itemType']=='ItemSpring: 15']
    assert entries and all(e['source']=='resolved_uninstantiated_block'and e['info']['<ObjectNearestPosX>k__BackingField']==0 for e in entries)
    assert any(e['custom']['_continuePop']for e in entries)
    assert not any('pending_item:ItemSpring'in s for s in model.unsupported)
    assert not model.spring_launches
    times=np.linspace(0.,1.8,217);hs,missing=hazard_forecasts(o,times,model)
    springs=[h for h in hs if h.kind=='ItemSpring'];assert len(springs)==len(entries)
    body,motors,valid=model.trajectory(times);assert valid
    pickup_body=model.interaction_bodies(motors)
    for h in springs:
        assert h.interaction and h.geometry=='obb'and h.padding>0
        assert min(clearance(pickup_body,h))>10.
        # Move the actual pickup capsule into the original trigger. A zero
        # damage box must still block an unmodelled pop/camera transition.
        near=pickup_body.copy();near[:,:2]+=h.centers[0]-pickup_body[0,:2]
        assert min(clearance(near,h))<0


@pytest.mark.parametrize('change',['hotfix','body','env','utility','callback','script','root_animation','root_motion',
 'behaviour','missing_animator','constraint','child_body','gravity','attraction','role_flag','spring_flag','projection',
 'rotate','direction','tilt','root_box','nan','unknown_custom','sync','base','initial_trigger'])
def test_unknown_reset_or_pre_contact_motion_still_refuses(change):
    o=deepcopy(DATA['observation']);t=o['spawn_templates']['spring'];e=deepcopy(DATA['cases'][0]['entry']);proof=t['item_base_reset']
    if change=='hotfix':t['source_stationary_reset']=False
    if change=='body':proof['body_equal']=False
    if change=='env':proof['environment_bound']=False
    if change=='utility':proof['utility_last']=401
    if change=='callback':t['callbacks_clear']=False
    if change=='script':t['component_types'].append('UnknownMover')
    if change=='root_animation':t['animated_root']=True
    if change=='root_motion':t['animators'][0]['apply_root_motion']=True
    if change=='behaviour':t['animators'][0]['behaviour_count']=1
    if change=='missing_animator':t['animators']=[]
    if change=='constraint':t['components'].append(dict(type='UnityEngine.Animations.ParentConstraint',on_root=True))
    if change=='child_body':t['components'].append(dict(type='UnityEngine.Rigidbody',on_root=False))
    if change=='gravity':t['physics']=dict(kinematic=False,gravity=True)
    if change=='attraction':t['global_attract']=True
    if change=='role_flag':o['role']['fields']['<AttractItemLevelValue>k__BackingField']=32
    if change=='spring_flag':o['role']['spring_attraction']=32
    if change=='projection':e['custom_projection']['complete']=False
    if change=='rotate':e['custom']['_needRotate']=True
    if change=='direction':t['direction_mode']='RightToLeft: 0'
    if change=='tilt':e['info']['_localEulerAngles']['x']=45.
    if change=='root_box':t['colliders'][0]['direct_root']=False
    if change=='nan':e['custom']['_popSpeed']=float('nan')
    if change=='unknown_custom':e['custom']['unknownMover']=1
    if change=='sync':e['sync_blocked']=True
    if change=='base':e['info']['baseID']=1
    if change=='initial_trigger':t['initial_is_trigger']=True
    assert pending_spring_contact(e,t,o)[0]is None


def test_missing_bound_channel_retains_the_original_unknown_effect_guard():
    o=deepcopy(DATA['observation']);o['spawn_templates']['spring'].pop('source_stationary_reset')
    model=PlayerModel(o);assert any('pending_item:ItemSpring'in s for s in model.unsupported)
