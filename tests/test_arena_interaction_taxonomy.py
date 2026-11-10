"""Original target semantics preserve collider shape and do not trust zero damage alone."""
from copy import deepcopy
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_yolo_obb_data import schema,physics_profile,targets
from arena_yolo_obb_score import interaction_confusions,match
from arena_obb_detector import decode


def native_profile():
    entities=[];prefabs={}
    for identity,name,script,shape,damage,species in [
        (280,'EnemyFruitBanana','EnemyFruitMuppet','BoxCollider',0,160031),
        (281,'EnemyFruitTomato','EnemyFruitPinball','CapsuleCollider',0,160031),
        (282,'EnemyFruitWatermelon','EnemyFruitPinball','CapsuleCollider',0,160031),
        (200,'EnemyMuppetBomb','EnemyMuppetBomb','SphereCollider',5,160008),
        (1,'UnknownZeroDamage','Other','SphereCollider',0,0)]:
        entities.append(dict(kind='enemies',type_id=identity,resource_name=name,
            config=dict(damage=damage,species=species),prefabs=[name]))
        prefabs[name]=dict(colliders=[dict(component=shape)],scripts=[dict(class_name=script)])
    return schema(entities,prefabs,[e['type_id']for e in entities])


def test_reviewed_fruit_and_bomb_roles_preserve_the_original_non_spherical_fruit_shapes():
    native=native_profile();profile=physics_profile(native,interactions=True)
    assert len(profile['classes'])==16
    for c,index in zip(native['classes'],profile['class_mapping']):
        mapped=profile['classes'][index]
        if c.get('resource')in ('EnemyFruitBanana','EnemyFruitTomato','EnemyFruitWatermelon')and c['shape']!='cue':
            assert mapped['kind']=='slice_target'and mapped['shape']==c['shape']
        elif c.get('resource')in ('EnemyMuppetBomb','UnknownZeroDamage')and c['shape']!='cue':
            assert mapped['kind']=='hazard'
    assert len(physics_profile(native)['classes'])==13


def test_a_same_named_prefab_with_different_original_script_or_damage_is_rejected():
    for field,value in [('script_types',['Other']),('configs',{'280':dict(damage=1,species=160031)})]:
        native=deepcopy(native_profile());native['families']['EnemyFruitBanana'][field]=value
        with pytest.raises(ValueError,match='Original interaction'):physics_profile(native,interactions=True)


def test_interaction_remapping_never_replaces_the_original_rotated_banana_box():
    native=native_profile();profile=physics_profile(native,interactions=True)
    quad=[dict(x=x,y=y)for x,y in [(300,180),(320,200),(300,220),(280,200)]]
    row=dict(label_schema=4,role=dict(colliders=[]),supports=[],objects=[dict(id=1,
        name='EnemyFruitBanana',family_type_id=280,renderers=[dict(box=[280,180,320,220])],
        colliders=[dict(type='BoxCollider',owner_id=1,tag='Enemy',plane_quad=quad)])])
    old,_=targets(row,native);new,_=targets(row,profile)
    assert old[0][1]==new[0][1]
    assert profile['classes'][new[0][0]]['name']=='fruit_box'


def test_localization_does_not_hide_a_high_confidence_danger_misclassified_as_a_target():
    classes=[dict(kind='hazard'),dict(kind='slice_target')]
    q=[[300,180],[320,180],[320,200],[300,200]];truth=[(0,q)]
    assert match(truth,[(1,q,.95)],classes,'physical')==[(0,0)]
    assert match(truth,[(1,q,.95)],classes,'geometry')==[]
    assert interaction_confusions(truth,[(1,q,.95)],classes)['policy_hazard_as_target']==1
    assert interaction_confusions(truth,[(1,q,.79)],classes)['policy_hazard_as_target']==0
    counts=interaction_confusions([(1,q)],[(1,q,.95)],classes)
    assert counts['policy_slice_as_target']==counts['policy_target_predictions']==1
    assert counts['policy_unmatched_targets']==0
    assert interaction_confusions([],[(1,q,.95)],classes)['policy_unmatched_targets']==1


def test_uncertain_fruit_prediction_is_still_an_obstacle_to_the_actor():
    p=dict(classes=[dict(kind='slice_target',shape='BoxCollider',motion_kind='slice_target')],target_policy_confidence=.8)
    q=[[[300,180],[320,180],[320,200],[300,200]]]
    assert decode(q,[0],[.95],p)[1][0].kind=='slice_target'
    assert decode(q,[0],[.79],p)[1][0].kind=='trap'
