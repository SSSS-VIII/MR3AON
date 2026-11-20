"""Full original pickup/first PopUp/PopFall, including before native birth."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-spring-launch.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_native_pickup_and_landing_use_original_render_collision_and_physical_lattices(case):
    o=case['before'];original=deepcopy(o);q=case['after'];model=PlayerModel(o)
    assert not model.unsupported and model.spring_launches
    dt=q['state']['time']-o['state']['time']
    body,motors,valid=model.trajectory(np.array([0.,dt]),case['operations'])
    target=q['role']['colliders'][0]
    assert valid and o==original
    assert np.linalg.norm(body[-1,:2]-[target['center'][a]for a in ('x','y')])<.002
    assert motors[-1].mode==q['state']['physics'].split(':')[0].lower()
    assert motors[-1].vx==pytest.approx(q['role']['velocity']['x'],abs=.0001)


def test_first_pop_tick_resets_offsets_then_applies_source_quadratic_velocity_once():
    o=DATA['cases'][0]['before'];model=PlayerModel(o)
    ts=np.arange(181)/60.;_,motors,valid=model.trajectory(ts)
    assert valid
    first=next(m for m in motors if m.mode=='popfall')
    assert first.vx==pytest.approx(24.375,abs=.00001)
    assert first.offset_field==first.offset_render==0.
    assert first.spring_ready and first.spring_event>0
    following=[m for m in motors if m.mode=='popfall']
    assert all(m.vx==first.vx for m in following)


@pytest.mark.parametrize('change',['lead','queue','parent','custom'])
def test_missing_birth_proof_remains_an_explicit_unmodelled_pending_item(change):
    o=deepcopy(DATA['cases'][0]['before']);e=o['pending_items'][0]
    if change=='lead':e['info']['generateDistance']=.1
    if change=='queue':
        p=deepcopy(e);p['id']='far-first-item';p['info_identity']=-1
        p['info']['_itemType']='ItemElementBall: 5'
        p['info']['<ObjectNearestPosX>k__BackingField']+=100.
        o['pending_items'].insert(0,p)
    if change=='parent':e['source']='resolved_uninstantiated_block'
    if change=='custom':e['custom_projection']=dict(complete=False,omitted=[dict(name='unknown',type='Object')])
    model=PlayerModel(o)
    assert 'pending_item:ItemSpring: 15'in model.unsupported
    assert e['id']not in model.modelled_pending_items


def test_consumed_native_spring_does_not_launch_again_from_enabled_trigger():
    o=deepcopy(DATA['cases'][2]['before']);assert not o['pending_items']
    for item in o['mechanism_items']:item['spring']['normal_active']=False
    model=PlayerModel(o)
    assert not model.spring_launches and not model.contact_avoidance


def test_skill_balls_are_not_misclassified_as_original_coin_counters():
    o=deepcopy(DATA['cases'][0]['before']);e=deepcopy(o['pending_items'][0])
    e['info']['_itemType']='ItemElementBall: 5';e['id']='ball';o['pending_items'].append(e)
    assert 'pending_item:ItemElementBall: 5'in PlayerModel(o).unsupported


def test_ambiguous_native_trigger_boundary_is_rejected_instead_of_guessing_pickup_tick():
    model=PlayerModel(DATA['cases'][0]['before']);m=deepcopy(model.initial)
    item=model.spring_launches[0];box=item['colliders'][0]
    m.x=min(p['x']for p in box['quad'])-model.pickup_profile[0]
    m.y=box['center']['y'];m.offset_render=0.
    assert not model.spring_launch(m,m,set(),model.tick)
