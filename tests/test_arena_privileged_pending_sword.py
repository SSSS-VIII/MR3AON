"""Original queue births are forecast before their EnemyBase is instantiated."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_policy import InternalController

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-pending-sword.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_native_unborn_sword_wait_charge_flight_boxes_are_enclosed(case):
    o=case['before'];original=deepcopy(o);q=case['after']
    assert not o['enemies']
    dt=q['state']['time']-o['state']['time'];times=np.linspace(0,dt,round(dt*120)+1)
    hs,missing=hazard_forecasts(o,times,PlayerModel(o))
    assert not missing and len(hs)==1 and o==original
    h=hs[0];c=next(c for c in q['enemy']['colliders']if c.get('damage_kind'))
    center=np.array([c['center'][a]for a in ('x','y')]);extent=np.array([c['extents'][a]for a in ('x','y')])
    assert h.active[-1]and np.all(abs(center-h.centers[-1])+extent<=h.extents[-1]+.0001)
    assert h.approximate and h.geometry=='aabb'and 'enemyList'in h.source
    assert q['enemy']['info_identity']==o['pending_enemies'][0]['info_identity']


def test_original_creation_removes_same_info_identity_from_actual_queue():
    for a,b in zip(DATA['queue_progression'],DATA['queue_progression'][1:]):
        born=set(b['live'])-set(a['live'])
        assert born and born<=set(a['pending'])
        assert born.isdisjoint(b['pending'])


@pytest.mark.parametrize('change,reason',[
    ('vertical','pending_vertical_spawn_gate'),
    ('source','pending_uninstantiated_block_initialization'),
    ('template','pending_sword_original_prefab_missing'),
    ('rotation','pending_sword_spatial_rotation'),
    ('breath','pending_sword_original_box_binding'),
    ('variant','pending_sword_original_variant'),
])
def test_pending_source_variants_cannot_disappear_as_an_empty_safe_lane(change,reason):
    o=deepcopy(DATA['cases'][0]['before']);e=o['pending_enemies'][0]
    if change=='vertical':e['vertical_gate']=True
    if change=='source':e['source']='resolved_uninstantiated_block'
    if change=='template':o['spawn_templates']['small_sword']['missing']=True
    if change=='rotation':e['info']['_localEulerAngles']['x']=30.
    if change=='breath':o['spawn_templates']['small_sword']['colliders'][0]['under_breath']=True
    if change=='variant':e['custom']['_render']=2
    hs,missing=hazard_forecasts(o,np.linspace(0.,.5,61),PlayerModel(o))
    assert not hs and missing==[dict(id=e['id'],type='EnemySmallSword',reason=reason)]
    assert InternalController().decide(o).reason=='unsupported_native_mechanism'


def test_blocked_and_unreachable_spawns_do_not_invent_existing_bodies():
    for blocked in (True,False):
        o=deepcopy(DATA['cases'][0]['before']);e=o['pending_enemies'][0]
        e['sync_blocked']=blocked
        if not blocked:e['info']['_localPosition']['x']+=1000
        hs,missing=hazard_forecasts(o,np.linspace(0.,.5,61),PlayerModel(o))
        assert not hs and not missing


def test_unknown_pending_family_is_rejected_even_without_a_live_enemy():
    o=deepcopy(DATA['cases'][0]['before']);o['pending_enemies'][0]['info']['_enemyType']='EnemyWarrior: 104'
    result=InternalController().decide(o)
    assert result.reason=='unsupported_native_mechanism'
    assert result.evidence['unsupported_enemies'][0]['reason']=='pending_spawn_initialization_not_modelled'
