"""A native eccentric-Box prior must not be assigned to unrelated boxes."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_yolo_obb_data import schema,physics_profile,targets


def ontology():
    entities=[dict(kind='enemies',type_id=100+i,resource_name=name,config={},prefabs=[name])
              for i,name in enumerate(['EnemyMace','EnemyGoldMace'])]
    box=dict(component='BoxCollider',local_to_prefab=np.eye(4).tolist(),
             geometry=dict(m_Size=dict(x=.45,y=1.9,z=1.),m_Center=dict(x=0.,y=1.4,z=0.)))
    from copy import deepcopy
    prefabs={name:dict(colliders=[deepcopy(box)],scripts=[dict(class_name='EnemyMace')])
             for name in ['EnemyMace','EnemyGoldMace']}
    return entities,prefabs


def test_source_bound_mace_keeps_physical_quad_and_adds_only_one_class():
    entities,prefabs=ontology();before=physics_profile(schema(entities,prefabs,[100]))
    after=physics_profile(schema(entities,prefabs,[100],mace_family=True))
    assert [c['name']for c in after['classes'][:-1]]==[c['name']for c in before['classes']]
    assert after['classes'][-1]['name']=='mace'
    assert after['classes'][-1]['pivot_offset_ratio']==pytest.approx(1.4/1.9)
    raw=dict(label_schema=4,role=dict(colliders=[]),supports=[],objects=[dict(id=1,type='EnemyMace',name='EnemyMace(Clone)',family_type_id=100,
        renderers=[dict(box=[300,180,320,250])],controller={},colliders=[dict(owner_id=1,type='BoxCollider',tag='Enemy',
        plane_quad=[dict(x=x,y=y)for x,y in [(300,180),(320,180),(320,250),(300,250)]])])])
    a,_=targets(raw,before);b,_=targets(raw,after)
    assert before['classes'][a[0][0]]['name']=='box_hazard'
    assert after['classes'][b[0][0]]['name']=='mace'and a[0][1]==b[0][1]


def test_gold_and_ordinary_mace_share_the_same_source_geometry_class():
    entities,prefabs=ontology();profile=physics_profile(schema(entities,prefabs,[100,101],mace_family=True))
    mace=[c for c in profile['classes']if c['name']=='mace']
    assert len(mace)==1 and len(mace[0]['members'])==2


def test_mace_name_without_original_script_is_rejected():
    entities,prefabs=ontology();prefabs['EnemyMace']['scripts']=[dict(class_name='OtherEnemy')]
    with pytest.raises(ValueError,match='script/collider'):schema(entities,prefabs,[100],mace_family=True)


def test_changed_eccentric_geometry_cannot_receive_old_pivot_prior():
    entities,prefabs=ontology();prefabs['EnemyMace']['colliders'][0]['geometry']['m_Center']['y']=0.
    with pytest.raises(ValueError,match='eccentric geometry'):schema(entities,prefabs,[100],mace_family=True)
