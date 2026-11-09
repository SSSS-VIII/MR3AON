import sys
from pathlib import Path
import pytest
pytest.importorskip('numpy')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_runtime_catalog import extend,ontology_plan


def test_spawned_resource_uses_original_config_and_exact_prefab_without_fabricating_placement():
    class Resources:
        containers={'assets/enemy/bullet.prefab':[(dict(bundle='original.ab'),dict(m_PathID=7))]}
        def prefab(self,*a):return dict(colliders=[dict(component='BoxCollider')],scripts=[])
    entities,prefabs,extra=extend([],{}, {153:dict(names=['Bullet'],scripts=['NativeBullet'])},
                                   {153:dict(ID=153,resourceName='Bullet',damage=5)},Resources())
    assert extra==[153]and entities[0]['config']['damage']==5
    assert entities[0]['gale_usage']['placements']==0 and entities[0]['runtime_generated']
    assert list(prefabs)==['original.ab::assets/enemy/bullet.prefab#7']


def test_missing_runtime_config_stays_raw_and_ambiguous_original_assets_raise():
    class Resources:
        containers={'a/bullet.prefab':[],'b/bullet.prefab':[]}
    entities,_,extra=extend([],{}, {153:{}},{},Resources())
    assert entities[0]['config']is None and entities[0]['resource_name']is None
    with pytest.raises(ValueError,match='unique'):
        extend([],{}, {153:{}},{153:dict(resourceName='Bullet')},Resources())


def test_spawned_ontology_does_not_fabricate_or_change_any_collection_entry():
    plan=dict(mode=6,reachable_enemy_types=[141],selected=[dict(spec=dict(board=8019),enemy_types=[141])])
    result=ontology_plan(plan,[153])
    assert result['reachable_enemy_types']==[141,153]and result['directly_placed_enemy_types']==[141]
    assert result['selected']==plan['selected']and plan['reachable_enemy_types']==[141]
