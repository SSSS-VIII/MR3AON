"""Arrow family supervision keeps original physical geometry and cue semantics."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_yolo_obb_data import schema,physics_profile,targets,supervision_quad
from arena_obb_detector import physical_quad
from arena_oriented import transform,rectangle
from arena_projection import SCALE
import numpy as np


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


def test_training_band_preserves_centerline_and_restores_original_collider():
    width=.07*SCALE;original=transform(((-40,-width/2),(40,-width/2),(40,width/2),(-40,width/2)),.7,(400,180))
    meta=dict(supervision_band_px=8.,inference_short_side_world=.07)
    trained=supervision_quad(meta,original);restored=physical_quad(trained,meta)
    assert np.mean(trained,axis=0)==pytest.approx((400,180),abs=.001)
    assert min(rectangle(trained)[1:3])==pytest.approx(8.,abs=.001)
    assert min(rectangle(restored)[1:3])==pytest.approx(width,abs=.001)
    assert max(rectangle(restored)[1:3])==pytest.approx(80.,abs=.001)
    # Order of the rectangle's corners is immaterial; the physical polygon is.
    from arena_yolo_obb_score import polygon_iou
    assert polygon_iou(original,restored)>.999


def test_unmarked_legacy_geometry_is_unchanged_by_band_codec():
    q=np.array([[1,100],[60,100],[60,104],[1,104]],float)
    assert np.array_equal(physical_quad(q,{}),q)
    assert np.array_equal(supervision_quad({},q),q)
