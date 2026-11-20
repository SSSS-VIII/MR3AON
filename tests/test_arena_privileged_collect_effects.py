"""Source-backed empty dispatch branches, not a universal harmless-coin label."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import collect_effect_issues,ordinary_red_coin,pending_item_issues
from types import SimpleNamespace

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-collect-effects.json').read_text())


def test_real_native_empty_lists_return_before_reading_cached_lua_tables():
    d=DATA['effects']
    assert d['buff_lua_present']and d['passive_lua_present']
    assert not collect_effect_issues(dict(collect_effects=d))
    for sample in DATA['native_samples']:
        assert sample['state']['health']==5000
        assert not collect_effect_issues(dict(collect_effects=sample['effects']))


@pytest.mark.parametrize('field', ['buff_count','buff_targets','buff_definitions','waiting_assist_buffs',
                                  'waiting_collision_buffs','passive_count','collect_listener_count'])
def test_nonempty_or_missing_effect_channel_cannot_be_treated_as_counter_only(field):
    for value in(1,-1,None):
        d=deepcopy(DATA['effects']);d[field]=value
        assert collect_effect_issues(dict(collect_effects=d))


@pytest.mark.parametrize('field',['present','native_dispatch','buff_manager_present',
                                 'passive_manager_present','message_manager_present'])
def test_missing_manager_or_replaced_dispatch_stops_the_physical_model(field):
    d=deepcopy(DATA['effects']);d[field]=False
    assert collect_effect_issues(dict(collect_effects=d))


@pytest.mark.parametrize('entry',DATA['entries'])
def test_red_coin_is_the_original_same_class_and_global_dispatch_is_actually_empty(entry):
    role=dict(collect_effects=DATA['effects'])
    assert ordinary_red_coin(entry,DATA['template'],dict(role=role))
    assert not ordinary_red_coin(entry,DATA['template'],dict(role={}))
    d=deepcopy(DATA['effects']);d['collect_listener_count']=1
    assert not ordinary_red_coin(entry,DATA['template'],dict(role=dict(collect_effects=d)))


@pytest.mark.parametrize('change',['kind','source','class','script','collider','custom','projection','render','event'])
def test_unbound_or_effectful_coin_lookalikes_remain_pending_issues(change):
    e=deepcopy(DATA['entries'][0]);t=deepcopy(DATA['template']);effects=deepcopy(DATA['effects'])
    if change=='kind':e['info']['_itemType']='ItemCoinCurve: 51'
    if change=='source':e['source']='authored_minus_live'
    if change=='class':t['type']='ItemCoinFish'
    if change=='script':t['component_types'].append('NinjaMover')
    if change=='collider':t['colliders']=[dict(type='BoxCollider')]
    if change=='custom':e['custom']['extra']=True
    if change=='projection':e['custom_projection']['complete']=False
    if change=='render':e['custom']['_render']=1
    if change=='event':effects['collect_event_name']='OtherEvent'
    assert not ordinary_red_coin(e,t,dict(role=dict(collect_effects=effects)))


def test_bound_red_pending_queue_no_longer_disagrees_with_already_supported_live_itemcoin():
    player=SimpleNamespace(observation=dict(pending_items=DATA['entries'],
        spawn_templates=dict(items=dict(ItemCoinRed=DATA['template'])),role=dict(collect_effects=DATA['effects'])),
        speed=14.,initial=SimpleNamespace(x=1960.08,vx=14.),spring_launches=[],
        interaction_radius=.42,modelled_pending_items=set())
    assert not pending_item_issues(player)
