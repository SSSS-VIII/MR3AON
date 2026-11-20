"""The native Bomb sphere offset is retained in inherited Spider activation."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts,clearance
from arena_privileged_families import spider_entry,progression_marker
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-muppet-entry.json').read_text())


def test_original_offset_root_sphere_is_not_erased_or_frozen_in_none_phase():
    o=DATA['observation'];original=deepcopy(o);e=o['enemies'][0]
    times=np.linspace(0.,1.8,217);hazards,missing=hazard_forecasts(o,times,PlayerModel(o))
    assert not missing and o==original and len(hazards)==1
    h=hazards[0];c=e['colliders'][0]
    np.testing.assert_allclose(h.centers[0],[c['center'][a]for a in ('x','y')],atol=1e-8)
    assert h.centers[-1,1]<h.centers[0,1]-8
    assert h.geometry=='aabb'and h.approximate
    # Activation uncertainty stretches Y only. A sphere would silently drop
    # that part of the forecast in the sphere/capsule distance formula.
    index=int(np.argmax(h.extents[:,1]));assert h.extents[index,1]>h.extents[index,0]+.1
    body=np.tile([h.centers[index,0],h.centers[index,1]-h.extents[index,1],.1,0.],(len(times),1))
    assert clearance(body,h)[index]<0


@pytest.mark.parametrize('case',DATA['pairs'],ids=lambda c:c['name'])
def test_original_bomb_activation_drop_flex_and_stay_pairs(case):
    o=case['before'];a=case['after'];dt=a['state']['time']-o['state']['time']
    times=np.linspace(0,dt,round(dt*120)+1);model=PlayerModel(o)
    _,states,valid=model.trajectory(times,tuple(tuple(v)for v in case['operations']))
    assert valid and o['state']['health']==a['state']['health']==5000
    hs,missing=hazard_forecasts(o,times,model,states)
    assert not missing and len(hs)==1
    h=hs[0];c=a['enemy']['colliders'][0]
    actual=np.array([c['center'][k]for k in ('x','y')]);ext=np.array([c['extents'][k]for k in ('x','y')])
    assert np.all(abs(actual-h.centers[-1])+ext<=h.extents[-1]+h.padding)


@pytest.mark.parametrize('change',['position','rotation','follow','owner','offset_on_spider'])
def test_offset_exception_requires_the_original_bomb_binding(change):
    o=deepcopy(DATA['observation']);e=o['enemies'][0];c=e['colliders'][0]
    if change=='position':c['position']['x']+=.1
    if change=='rotation':c['rotation_z']+=10
    if change=='follow':c['spine_follow']={'bone_name':'weapon'}
    if change=='owner':c['damage_owner']+=1
    if change=='offset_on_spider':e['type']='EnemySpider'
    path,reason=spider_entry(e,np.array([0.,.5]),o,PlayerModel(o))
    assert path is None and reason=='spider_unverified_entry_shape'


def test_original_resurgence_event_sets_a_region_flag_without_moving_a_live_role():
    o=DATA['before_event'];original=deepcopy(o);item=o['mechanism_items'][0]
    assert progression_marker(item)=='special_resurgence_start'
    assert not PlayerModel(o).unsupported and o==original
    end=deepcopy(item)
    g=end['action_data']['fields']['_levelActionDataList']['items'][0]['fields']['_finalParamList']['items'][0]['fields']
    g['_controllType']='EndSepcialResurgence: 55'
    assert progression_marker(end)=='special_resurgence_end'


def test_native_original_marker_pickup_preserves_healthy_motion_and_sets_flag():
    pair=DATA['event_pair'];before=pair['before'];after=pair['after']
    assert pair['special_resurgence']is True
    assert before['state']['health']==after['state']['health']==5000
    assert not before['role']['god']and not after['role']['god']
    assert before['state']['position']['x']<after['state']['position']['x']
    assert progression_marker(before['mechanism_items'][0])=='special_resurgence_start'
    assert not after['mechanism_items']
    dt=after['state']['time']-before['state']['time'];times=np.linspace(0,dt,round(dt*120)+1)
    body,states,valid=PlayerModel(before).trajectory(times)
    assert valid and states[-1].mode==after['state']['physics'].split(':')[0].lower()
    assert abs(states[-1].y-after['state']['position']['y'])<.001


@pytest.mark.parametrize('change',['truncated','nested_truncated','object_truncated','action_truncated','group_truncated','another_action','another_control','execution','empty','bad_time'])
def test_a_marker_cannot_hide_another_event_action(change):
    o=deepcopy(DATA['before_event']);item=o['mechanism_items'][0]
    sequence=item['action_data']['fields']['_levelActionDataList'];action=sequence['items'][0]['fields']
    groups=action['_finalParamList'];g=groups['items'][0]['fields']
    if change=='truncated':sequence['truncated']=True
    if change=='nested_truncated':groups['truncated']=True
    if change=='object_truncated':item['action_data']['truncated']=True
    if change=='action_truncated':sequence['items'][0]['truncated']=True
    if change=='group_truncated':groups['items'][0]['truncated']=True
    if change=='another_action':action['_actionType']='MoveNinja: 0'
    if change=='another_control':g['_controllType']='LevelFinish: 0'
    if change=='execution':g['_exeType']='Other: 99'
    if change=='empty':groups['items']=[]
    if change=='bad_time':g['_nextGroupTime']=float('nan')
    assert progression_marker(item)is None
    assert 'item:ItemEvent'in PlayerModel(o).unsupported
