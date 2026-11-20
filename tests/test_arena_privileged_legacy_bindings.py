"""Legacy catalog bindings require actual original instances, not enum guesses."""
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_catalog import dependencies,NATIVE_BINDINGS
from arena_privileged_model import PlayerModel,hazard_forecasts
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-legacy-bindings.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:str(c['type_id']))
def test_catalog_uses_original_runtime_class_and_keeps_route_acceptance_pending(case):
    binding=case['binding'];identity=case['type_id']
    assert binding['active']and case['enemy']['type']==binding['type']
    assert binding['enemy_type']==case['enemy']['info']['_enemyType']
    inventory=dict(contexts=[dict(key='test',stage=1,kind='ordinary')],counts=dict(unique_fixed=1,contexts=1),
        stages={'1':dict(mechanism=dict(kind='ordinary',enemy_type_counts={str(identity):1},item_type_counts={}))})
    result=dependencies(inventory,[dict(kind='enemies',type_id=identity,prefabs=[])],{})
    row=result['cases']['test'];assert row['enemy_classes']==[binding['type']]
    assert not row['unbound_enemy_ids']and not row['unimplemented_enemy_classes']
    assert not row['native_no_damage']and not row['timing_robust']


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:str(c['type_id']))
def test_bound_live_future_matches_original_client_shape(case):
    o=case['before'];target=case['enemy'];times=np.linspace(0.,case['seconds'],13)
    hs,missing=hazard_forecasts(o,times,PlayerModel(o))
    assert not any(m['id']==target['id']for m in missing)
    hazards=[h for h in hs if h.enemy==target['id']];assert hazards
    truth={c['id']:c for e in case['after']['enemies']for c in e['colliders']};checked=0
    for h in hazards:
        c=truth[h.id]
        if not c['enabled']or not c['active']:continue
        actual=np.array([c['center'][a]for a in('x','y')])
        assert np.linalg.norm(actual-h.centers[-1])<.0002;checked+=1
    assert checked


def test_unobserved_legacy_id_is_not_inferred_from_a_similar_enum_or_custom_type():
    assert 227 not in NATIVE_BINDINGS
    inventory=dict(contexts=[dict(key='test',stage=1,kind='ordinary')],counts=dict(unique_fixed=1,contexts=1),
        stages={'1':dict(mechanism=dict(kind='ordinary',enemy_type_counts={'227':1},item_type_counts={}))})
    row=dependencies(inventory,[dict(kind='enemies',type_id=227,prefabs=[])],{})['cases']['test']
    assert row['unbound_enemy_ids']==[227]and not row['enemy_classes']
