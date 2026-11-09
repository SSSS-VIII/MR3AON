import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_yolo_obb_data import schema,targets,clipped_quad,segment_quad,build,physics_profile


def profile():
    entities=[dict(kind='enemies',type_id=101,resource_name='Crow',config={},prefabs=['crow']),
              dict(kind='enemies',type_id=102,resource_name='Crow',config={},prefabs=['crow'])]
    prefabs={'crow':dict(colliders=[dict(component='SphereCollider')],scripts=[dict(class_name='EnemyStraightBat')])}
    return schema(entities,prefabs,[101,102,238])


def test_ontology_keeps_raw_unknowns_and_deduplicates_shared_original_resource():
    p=profile();names=[c['name']for c in p['classes']]
    assert p['type_bindings']['101']==p['type_bindings']['102']=='Crow'
    assert p['type_bindings']['238']=='type_238'
    assert len(names)==len(set(names))
    assert 'Crow__SphereCollider__ready'in names
    assert 'Crow__BoxCollider__normal'not in names
    assert any(c['kind']=='floating_platform'for c in p['classes'])


def test_compound_collider_and_visible_cue_labels_preserve_physical_shape_and_phase():
    p=profile()
    row=dict(label_schema=4,role=dict(colliders=[]),supports=[],objects=[
        dict(id=1,name='Crow',family_type_id=101,renderers=[dict(box=[300,200,330,230])],
             controller={'_currState':'ready: 3'},colliders=[dict(type='SphereCollider',box=[300,200,330,230],
             owner_id=1,layer=17,tag='Enemy')]),
        dict(id=2,name='unknown',family_type_id=238,renderers=[dict(box=[400,180,420,200])],colliders=[])])
    labels,stats=targets(row,p)
    assert [p['classes'][c]['name']for c,q in labels]==['Crow__SphereCollider__ready','type_238__cue__normal']
    row['objects'][0]['colliders'][0]['owner_id']=2
    with pytest.raises(ValueError,match='ownership'):targets(row,p)


def test_sloped_support_has_an_oriented_thin_label_and_clipping_stays_in_normalized_range():
    q=segment_quad(dict(x=-100,y=280),dict(x=700,y=180))
    clipped=clipped_quad(q)
    assert clipped is not None and clipped.shape==(4,2)
    assert (clipped>=[0,0]).all()and(clipped<=[640,360]).all()
    edges=np.roll(clipped,-1,axis=0)-clipped
    longest=edges[np.argmax(np.linalg.norm(edges,axis=1))]
    assert abs(longest[0])>600 and abs(longest[1])>40


def test_old_incomplete_support_rows_are_not_silently_used_as_negative_rope_images():
    with pytest.raises(ValueError,match='schema 4'):targets(dict(label_schema=3),profile())


def test_obb_scoring_distinguishes_physical_location_from_resource_and_attack_phase():
    from arena_yolo_obb_score import match
    p=profile();classes=p['classes'];names=[c['name']for c in classes]
    ready=names.index('Crow__SphereCollider__ready');rush=names.index('Crow__SphereCollider__rush')
    q=[[300,200],[330,200],[330,230],[300,230]]
    truth=[(ready,q)];predicted=[(rush,q,.9)]
    assert not match(truth,predicted,classes)
    assert match(truth,predicted,classes,'resource')==[(0,0)]
    assert match(truth,predicted,classes,'geometry')==[(0,0)]


def test_true_rotated_box_corners_are_not_replaced_by_the_projected_bounding_cube():
    from arena_yolo_obb_score import polygon_iou
    p=profile();quad=[[300,200],[310,190],[330,210],[320,220]]
    row=dict(label_schema=4,role=dict(colliders=[]),supports=[],objects=[
        dict(id=8,name='electric',family_type_id=238,renderers=[dict(box=[250,150,400,280])],
             colliders=[dict(type='BoxCollider',owner_id=8,tag='Enemy',layer=9,box=[250,150,400,280],
                             plane_quad=[dict(x=x,y=y)for x,y in quad])])])
    labels,_=targets(row,p)
    assert p['classes'][labels[0][0]]['shape']=='BoxCollider'
    assert polygon_iou(labels[0][1],quad)>.999


def test_copied_folders_from_one_map_seed_cannot_leak_across_train_and_validation(tmp_path):
    import json
    train=tmp_path/'train';val=tmp_path/'val';train.mkdir();val.mkdir()
    for folder in(train,val):(folder/'setup.json').write_text(json.dumps(dict(seed=1,level=2,map=11)))
    with pytest.raises(ValueError,match='map seed'):
        build(tmp_path/'out',[train],[val],tmp_path/'entities',tmp_path/'prefabs',tmp_path/'plan')


def test_shared_physics_classes_retain_original_ontology_and_separate_attack_phase():
    native=profile();shared=physics_profile(native)
    assert len(shared['classes'])==13 and shared['type_bindings']==native['type_bindings']
    names=[c['name']for c in native['classes']]
    assert shared['class_mapping'][names.index('Crow__SphereCollider__ready')]==6
    assert shared['class_mapping'][names.index('Crow__SphereCollider__rush')]==7
    assert shared['class_mapping'][names.index('type_238__BoxCollider__normal')]==4
    assert shared['class_mapping'][names.index('type_238__SphereCollider__normal')]==5
    assert shared['native_targets']['families']['Crow']['type_ids']==[101,102]
