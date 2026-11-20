"""Native score pickup/fragments, including an uninstantiated nearest-X=0."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import skull_source_binding,pending_item_issues,static_skull,configure_pending_pickups

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-skull.json').read_text())


def test_all_original_renderer_assets_are_noncolliding_sprite_modules():
    assets=DATA['assets']
    assert {int(v['assets'][0].split('_')[-1].split('.')[0])for v in assets}==set(range(1,29))
    for entry in assets:
        assert not entry['errors']and entry['scripts']==['FissonableModule']
        assert set(entry['types'])=={'AssetBundle','GameObject','MonoBehaviour','MonoScript','SpriteRenderer','Transform'}
        assert len(entry['sha256'])==64


@pytest.mark.parametrize('entry',DATA['live']+DATA['pending'])
def test_original_pending_and_live_pickups_bind_root_only_trigger_geometry(entry):
    original=deepcopy(entry)
    assert skull_source_binding(entry,DATA['template'],live='type'in entry)
    assert entry==original


@pytest.mark.parametrize('change',['render','index','custom','projection','independent','source',
                                   'hook','script','animation','collider','gravity','missing'])
def test_unknown_renders_initializers_and_template_effects_are_not_ignored(change):
    e=deepcopy(DATA['pending'][0]);t=deepcopy(DATA['template'])
    if change=='render':e['custom']['_renderType']='skull_29: 28'
    if change=='index':e['custom']['_renderType']='skull_4: 4'
    if change=='custom':e['custom']['extra']=True
    if change=='projection':e['custom_projection']['complete']=False
    if change=='independent':e['info']['independentAnim']=True
    if change=='source':e['source']='invented_queue'
    if change=='hook':t['native_skull_callbacks']=False
    if change=='script':t['component_types'].append('DamageScript')
    if change=='animation':t['animated_tree']=True
    if change=='collider':t['colliders'].append(dict(type='SphereCollider'))
    if change=='gravity':t['gravity']=True
    if change=='missing':t={}
    assert not skull_source_binding(e,t)


@pytest.mark.parametrize('change',['callback','script','animation','collider','damage','render','gravity'])
def test_live_added_damage_or_movement_components_still_stop_the_model(change):
    e=deepcopy(DATA['live'][0]);b=e['skull_binding']
    if change=='callback':b['callbacks_clear']=False
    if change=='script':b['component_types'].append('EnemyBaseCollider')
    if change=='animation':b['animated']=True
    if change=='collider':e['colliders'].append(deepcopy(e['colliders'][0]))
    if change=='damage':e['colliders'][0]['damage_kind']='enemy_callback'
    if change=='render':e['fields']['_renderType']=7
    if change=='gravity':b['gravity']=True
    assert not skull_source_binding(e,DATA['template'],live=True)


def test_uninitialized_nearest_point_is_not_a_generic_distant_item_escape():
    entries=deepcopy(DATA['pending'])
    assert all(e['info']['<ObjectNearestPosX>k__BackingField']==0 for e in entries)
    player=SimpleNamespace(observation=dict(pending_items=entries,
        spawn_templates=dict(items=dict(ItemSkull=DATA['template'])),role=DATA['role']),
        initial=SimpleNamespace(x=820.1893,vx=14.),speed=14.,spring_launches=[],
        interaction_radius=.42,modelled_pending_items=set(),contact_avoidance=[])
    configure_pending_pickups(player)
    assert not pending_item_issues(player)and len(player.contact_avoidance)==2
    assert min(i['colliders'][0]['center']['x']for i in player.contact_avoidance)>900
    player.modelled_pending_items.clear()
    entries[0]['custom']['_renderType']='skull_29: 28'
    configure_pending_pickups(player)
    assert pending_item_issues(player)==['pending_item:ItemSkull: 14']
    entries[0]['info']['_itemType']='ItemUnknown: 999'
    assert pending_item_issues(player)==['pending_item:ItemUnknown: 999']


@pytest.mark.parametrize('entry',DATA['live'])
def test_original_live_reset_pose_matches_the_single_native_trigger(entry):
    item,reason=static_skull(entry,DATA['template'],dict(role=DATA['role']),live=True)
    assert reason is None and item['colliders']==entry['colliders']


@pytest.mark.parametrize('change',['flag','spring','override','rotation','moving','consumed'])
def test_motion_attraction_and_consumed_effects_do_not_become_static_empty_space(change):
    e=deepcopy(DATA['live'][0]);t=deepcopy(DATA['template']);role=deepcopy(DATA['role'])
    if change=='flag':role['fields']['<AttractItemLevelValue>k__BackingField']=32
    if change=='spring':role['spring_attraction']=32
    if change=='override':t['global_attract']=True
    if change=='rotation':e['info']['_localEulerAngles']['x']=1
    if change=='moving':e['fields']['beAttracting']=True
    if change=='consumed':e['colliders'][0]['enabled']=False
    item,reason=static_skull(e,t,dict(role=role),live=True)
    assert item is None and reason
