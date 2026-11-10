"""Arrow family supervision keeps original physical geometry and cue semantics."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_yolo_obb_data import schema,physics_profile,targets


def ontology():
    entities=[dict(kind='enemies',type_id=213,resource_name='EnemyArrow',config={},prefabs=['arrow']),
              dict(kind='enemies',type_id=214,resource_name='EnemyArrowWarning',config={},prefabs=['warning'])]
    prefabs=dict(arrow=dict(colliders=[dict(component='BoxCollider')],scripts=[dict(class_name='EnemyArrow')]),
                 warning=dict(colliders=[],scripts=[dict(class_name='EnemyArrowWarning')]))
    return entities,prefabs


def test_arrow_is_a_source_bound_family_not_every_long_or_rotated_box():
    entities,prefabs=ontology();old=physics_profile(schema(entities,prefabs,[213,214]))
    new=physics_profile(schema(entities,prefabs,[213,214],arrow_family=True))
    assert [c['name']for c in new['classes'][:13]]==[c['name']for c in old['classes']]
    assert new['classes'][-1]['name']=='arrow'and new['classes'][-1]['motion_kind']=='arrow'
    raw=dict(label_schema=4,role=dict(colliders=[]),supports=[],objects=[dict(id=1,type='EnemyArrow',
        name='EnemyArrow(Clone)',family_type_id=213,renderers=[dict(box=[300,180,370,200])],controller={},
        colliders=[dict(owner_id=1,type='BoxCollider',tag='Enemy',box=[300,180,370,200],
            plane_quad=[dict(x=x,y=y)for x,y in [(300,180),(370,180),(370,200),(300,200)]])])])
    before,_=targets(raw,old);after,_=targets(raw,new)
    assert old['classes'][before[0][0]]['name']=='box_hazard'
    assert new['classes'][after[0][0]]['name']=='arrow'
    assert before[0][1]==after[0][1]
    warning=[c for c in new['native_targets']['classes']if c.get('resource')=='EnemyArrowWarning']
    assert warning and all(c['kind']=='cue'for c in warning)


def test_resource_name_without_original_script_is_rejected():
    entities,prefabs=ontology();prefabs['arrow']['scripts']=[dict(class_name='OtherEnemy')]
    with pytest.raises(ValueError,match='script/collider'):
        schema(entities,prefabs,[213,214],arrow_family=True)
