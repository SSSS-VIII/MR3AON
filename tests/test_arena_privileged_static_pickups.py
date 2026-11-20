"""Original static pickup shape and callback binding, before and after birth."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import static_pickup,coin_only_magnet,passive_fixed_item
from arena_privileged_model import PlayerModel,hazard_forecasts

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-static-pickups.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_native_static_pickup_birth_geometry_and_later_curve_phase_remain_bound(case):
    original=deepcopy(case)
    model,reason=static_pickup(case['entry'],case['template'],dict(role=case['before_role']))
    assert reason is None
    actual=case['first_live']['colliders'][0];predicted=model['colliders'][0]
    for key in ('center','extents'):
        assert np.allclose([actual[key][a]for a in ('x','y','z')],
                           [predicted[key][a]for a in ('x','y','z')],atol=.0002,rtol=0)
    model,reason=static_pickup(case['first_live'],case['template'],dict(role=case['after_role']),live=True)
    assert reason is None and model['colliders'][0]==actual and case==original


@pytest.mark.parametrize('change',['role_flag','spring_flag','override','manager','animated','script',
                                   'speed','omission','rotation','collider'])
def test_unproved_motion_attraction_and_prefabs_do_not_become_static_pickups(change):
    case=deepcopy(DATA['cases'][0]);entry=case['entry'];template=case['template'];role=case['before_role']
    if change=='role_flag':role['fields']['<AttractItemLevelValue>k__BackingField']=32
    if change=='spring_flag':role['spring_attraction']=32
    if change=='override':template['global_attract']=True
    if change=='manager':template['attraction_manager_present']=False
    if change=='animated':template['animated_tree']=True
    if change=='script':template['root_scripts'].append('ExtraMover')
    if change=='speed':entry['custom']['_speedX']=5.
    if change=='omission':entry['custom_projection']['complete']=False
    if change=='rotation':entry['info']['_localEulerAngles']['z']=90.
    if change=='collider':template['colliders'][0]['direct_root']=False
    item,reason=static_pickup(entry,template,dict(role=role))
    assert item is None and reason


def test_source_normal_magnet_only_adds_lower_coin_flag_and_does_not_grant_protection():
    case=next(c for c in DATA['cases']if c['name']=='ItemMagnet')
    assert coin_only_magnet(case['entry'],case['template'])
    assert coin_only_magnet(case['first_live'],case['template'])
    changed=deepcopy(case['template']);changed['attract_item_level']=32
    assert not coin_only_magnet(case['entry'],changed)


def test_native_water_ball_is_still_avoided_while_coin_only_magnet_is_modelled():
    o=DATA['observation'];model=PlayerModel(o)
    assert not model.unsupported
    hs,missing=hazard_forecasts(o,np.linspace(0,1.8,217),model)
    assert not missing
    assert sum(h.kind=='ItemElementBall'for h in hs)==1
    assert not any(h.kind=='ItemMagnet'for h in hs)
    assert next(h for h in hs if h.kind=='ItemElementBall').interaction


@pytest.mark.parametrize('change',[None,'collider','script','animation','attraction','custom'])
def test_only_verified_noncolliding_nonanimated_fixed_render_is_inert(change):
    f=deepcopy(DATA['fixed']);item,template,role=f['item'],f['template'],f['role']
    if change=='collider':item['colliders']=[dict(type='BoxCollider')]
    if change=='script':item['component_types'].append('EnemySpawner')
    if change=='animation':item['animated_tree']=True
    if change=='attraction':role['fields']['<AttractItemLevelValue>k__BackingField']=32
    if change=='custom':item['custom']['actionLook']=1
    assert passive_fixed_item(item,template,dict(role=role),live=True)==(change is None)
