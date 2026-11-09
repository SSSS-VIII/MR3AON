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
    assert stats['resource:Crow']==1 and stats['resource:type_238']==0
    assert stats['type:238']==0
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


def test_thin_support_line_metric_distinguishes_pixel_error_from_missing_geometry():
    from arena_yolo_obb_score import match,match_support_lines
    p=profile();classes=p['classes'];rope=next(i for i,c in enumerate(classes)if c['kind']=='rope')
    def q(x1,x2,y):return segment_quad(dict(x=x1,y=y),dict(x=x2,y=y)).tolist()
    truth=[(rope,q(0,640,260))];predicted=[(rope,q(0,640,263),.9)]
    assert not match(truth,predicted,classes)
    assert match_support_lines(truth,predicted,classes)==[(0,0,3.)]
    assert not match_support_lines(truth,[(rope,q(0,100,260),.9)],classes)
    assert not match_support_lines(truth,[(rope,q(0,640,270),.9)],classes)


def test_native_zero_type_clone_requires_both_exact_prefab_root_and_original_script():
    from arena_yolo_obb_data import object_resource
    p=profile()
    obj=dict(family_type_id=0,source_type_id=0,name='Crow(Clone)(Clone)',type='EnemyStraightBat')
    assert object_resource(obj,p)=='Crow'
    assert object_resource(dict(obj,type='Unknown'),p)is None
    assert object_resource(dict(obj,name='CrowFake(Clone)'),p)is None
    assert object_resource(dict(obj,family_type_id=238,name='Crow'),p)=='type_238'


def test_shared_model_keeps_original_resource_recall_without_claiming_identity_precision():
    from arena_yolo_obb_score import resource_recalls
    p=profile();shared=physics_profile(p)
    crow=next(i for i,c in enumerate(p['classes'])if c['name']=='Crow__SphereCollider__normal')
    other=next(i for i,c in enumerate(p['classes'])if c['name']=='type_238__SphereCollider__normal')
    q=[[300,200],[330,200],[330,230],[300,230]];r=[[400,200],[430,200],[430,230],[400,230]]
    native=[(crow,q),(other,r)];mapped=[(shared['class_mapping'][c],b)for c,b in native]
    # One shared shape prediction cannot cover a separate, missed resource.
    result=resource_recalls(native,mapped,[(2,q,.9)],p['classes'],shared['classes'])
    assert result['Crow']['targets']==1 and result['Crow']['matched']==1
    assert result['type_238']['targets']==1 and result['type_238']['matched']==0
    assert 'precision'not in result['Crow']


def test_support_training_band_changes_only_padding_while_physical_centerline_stays_exact():
    from arena_obb_detector import support_segment
    p=profile();row=dict(label_schema=4,role=dict(colliders=[]),objects=[],
                        supports=[dict(kind='rope',start=dict(x=50,y=260),finish=dict(x=590,y=260))])
    narrow,_=targets(row,p);wide,_=targets(row,dict(p,support_band_px=12))
    assert support_segment(narrow[0][1])==support_segment(wide[0][1])==((50.,260.),(590.,260.))
    a=np.asarray(narrow[0][1]);b=np.asarray(wide[0][1])
    assert np.ptp(a[:,1])==4 and np.ptp(b[:,1])==12
    from arena_yolo_obb_score import centerline_truth
    fixed=centerline_truth(row,dict(p,support_band_px=12),wide)
    assert np.ptp(np.asarray(fixed[0][1])[:,1])==4


def test_unknown_visible_spawn_is_reported_instead_of_becoming_silent_background():
    p=profile();quad=[dict(x=x,y=y)for x,y in [(300,180),(330,180),(330,210),(300,210)]]
    obj=dict(id=7,name='SpawnedBullet',type='NativeBullet',family_type_id=153,renderers=[dict(box=[300,180,330,210])],
             colliders=[dict(owner_id=7,tag='Enemy',type='BoxCollider',plane_quad=quad)])
    row=dict(label_schema=4,role=dict(colliders=[]),objects=[obj],supports=[])
    labels,stats=targets(row,p)
    assert not labels and stats['unbound_visible_targets']==1 and stats['unbound_visible_type:153']==1
    for point in quad:point['x']+=1000
    assert targets(row,p)[1]['unbound_visible_targets']==0


def test_revisited_training_seed_in_another_collection_cannot_overwrite_episode_images(tmp_path):
    import json
    folders=[tmp_path/'first'/'train-w00-s1-a1',tmp_path/'second'/'train-w00-s1-a1']
    for folder in folders:
        folder.mkdir(parents=True)
        (folder/'setup.json').write_text(json.dumps(dict(seed=1,level=1,map=1)))
        (folder/'labels.jsonl').write_text(json.dumps(dict(label_schema=4,image='000000.png',role=dict(colliders=[]),objects=[],supports=[]))+'\n')
        (folder/'000000.png').write_bytes(b'original frame placeholder')
    for name,value in [('entities',[]),('prefabs',{}),('plan',dict(mode=6,reachable_enemy_types=[]))]:
        (tmp_path/name).write_text(json.dumps(value))
    out=tmp_path/'data';manifest=build(out,folders,[],tmp_path/'entities',tmp_path/'prefabs',tmp_path/'plan')
    assert manifest['splits']['train']['counts']['frames']==2
    images=list((out/'images/train').iterdir())
    assert len(images)==2 and {p.resolve()for p in images}=={(f/'000000.png').resolve()for f in folders}
