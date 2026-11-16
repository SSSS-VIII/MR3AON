"""Untagged weapons require original component/owner proof, not visual guesses."""
from pathlib import Path
from copy import deepcopy
import json
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_damage_modules import build_registry,is_damage_collider,attach_damage_modules

SOURCE=json.loads((Path(__file__).parent/'fixtures/arena-attack-module-source.json').read_text())


def registry(tmp_path):
    root=tmp_path/'trees';bundle=root/SOURCE['bundle'];bundle.mkdir(parents=True)
    for name,value in SOURCE['files'].items():(bundle/name).write_text(json.dumps(value))
    return build_registry(root)


def native_collider(binding,**changes):
    row=dict(owner_id=12,name=binding['collider_name'],type=binding['collider_type'],tag='Untagged',
             **deepcopy(binding['signature']))
    row.update(changes)
    return row


def owner(binding):
    return dict(id=12,name=binding['owner_name']+'(Clone)(Clone)',type=binding['owner_class'])


def test_original_axe_has_an_explicit_damage_callback_and_untagged_collider(tmp_path):
    result=registry(tmp_path);binding,=result['bindings']
    assert result['counts']['untagged_bindings']==1
    assert result['counts']['detached_bindings']==0 and not result['unresolved']
    assert binding['owner_class']=='EnemyPoleaxeWarrior'and binding['collider_name']=='axe'
    assert binding['signature']['size']==pytest.approx(dict(x=1.13,y=2.35,z=1.))
    assert binding['owner_component']==-2671468648480661154
    assert result['source_sha256']and len(result['inputs_digest_sha256'])==64
    assert is_damage_collider(owner(binding),native_collider(binding),result['bindings'])


def test_old_profiles_require_explicit_source_retrofit_and_keep_their_geometry(tmp_path):
    result=registry(tmp_path);binding=result['bindings'][0]
    profile={'taxonomy':'physics','classes':[{'name':'box_hazard'}],'native_targets':{'families':{}}}
    before=deepcopy(profile);updated=attach_damage_modules(profile,result)
    assert profile==before and updated['classes']==profile['classes']
    assert updated['native_targets']['source_damage_modules']==result['bindings']
    assert len(updated['damage_modules_sha256'])==64
    assert not is_damage_collider(owner(binding),native_collider(binding))


@pytest.mark.parametrize('changes',[
    {'name':'PickupArea'}, {'type':'SphereCollider'},
    {'size':dict(x=1.2,y=2.35,z=1.)}, {'center':dict(x=.4,y=0.,z=0.)},
    {'tag':'Player'},
])
def test_auxiliary_or_mismatched_colliders_do_not_inherit_axe_damage(tmp_path,changes):
    result=registry(tmp_path);binding=result['bindings'][0]
    assert not is_damage_collider(owner(binding),native_collider(binding,**changes),result['bindings'])


def test_owner_prefab_and_class_must_both_match_source(tmp_path):
    result=registry(tmp_path);binding=result['bindings'][0];obj=owner(binding)
    assert not is_damage_collider(dict(obj,name='OtherEnemy'),native_collider(binding),result['bindings'])
    assert not is_damage_collider(dict(obj,type='OtherClass'),native_collider(binding),result['bindings'])
    assert not is_damage_collider(obj,native_collider(binding),[dict(binding,signature={})])


def test_native_callback_accepts_new_valid_names_without_static_shape_guessing():
    obj=dict(id=12,name='RuntimeEnemy',type='RuntimeEnemy')
    c=dict(owner_id=12,name='new_damage_part',type='BoxCollider',tag='Untagged',
           damage_callback=dict(kind='EnemyAttackModule',owner_id=12))
    assert is_damage_collider(obj,c)
    assert not is_damage_collider(obj,dict(c,damage_callback=dict(kind='OtherTrigger',owner_id=12)))
    with pytest.raises(ValueError,match='callback ownership'):
        is_damage_collider(obj,dict(c,damage_callback=dict(kind='EnemyAttackModule',owner_id=99)))
    with pytest.raises(ValueError,match='collider ownership'):
        is_damage_collider(obj,dict(c,owner_id=99))


def test_missing_source_owner_is_reported_instead_of_invented(tmp_path):
    root=tmp_path/'trees';bundle=root/SOURCE['bundle'];bundle.mkdir(parents=True)
    for name,value in SOURCE['files'].items():
        value=deepcopy(value)
        if name=='-7953010125049378766.MonoBehaviour.json':value['_belongToEnemy']={'m_FileID':1,'m_PathID':1}
        (bundle/name).write_text(json.dumps(value))
    result=build_registry(root)
    assert not result['bindings']and result['counts']['unresolved']==1


def test_source_enemy_body_is_not_implicitly_a_separate_attack_module(tmp_path):
    result=registry(tmp_path)
    assert all(b['collider_name']!='Warrior'for b in result['bindings'])
    obj=dict(id=12,name='anything',type='anything')
    assert is_damage_collider(obj,dict(owner_id=12,tag='Enemy'))


def test_native_target_preparation_adds_the_weapon_and_keeps_unrelated_auxiliary(tmp_path):
    pytest.importorskip('cv2')
    from arena_yolo_obb_data import targets
    result=registry(tmp_path);binding=result['bindings'][0];obj=owner(binding)
    def quad(x,y,w,h):return [dict(x=x,y=y),dict(x=x+w,y=y),dict(x=x+w,y=y+h),dict(x=x,y=y+h)]
    body=dict(owner_id=12,name='Warrior',type='BoxCollider',tag='Enemy',plane_quad=quad(400,210,96,25))
    axe=native_collider(binding,plane_quad=quad(170,190,40,65))
    pickup=native_collider(binding,name='PickupArea',plane_quad=quad(170,190,50,70))
    obj.update(family_type_id=256,renderers=[dict(name='Warrior',box=[150,140,500,260])],
               colliders=[body,axe,pickup])
    profile=dict(classes=[dict(name='player',kind='player',shape='CapsuleCollider'),
                    dict(name='poleaxe_box',kind='hazard',resource='EnemyPoleaxeWarrior',shape='BoxCollider',phase='normal',type_ids=[256])],
                 families={'EnemyPoleaxeWarrior':dict(straight_bat=False)},type_bindings={'256':'EnemyPoleaxeWarrior'})
    raw=dict(label_schema=4,role=dict(colliders=[]),objects=[obj],supports=[])
    original,old=targets(raw,profile)
    updated,stats=targets(raw,attach_damage_modules(profile,result))
    assert len(original)==1 and len(updated)==2
    assert old['auxiliary_colliders']==2 and stats['auxiliary_colliders']==1
    assert stats['damage_module_visible_targets']==1
    assert updated[0][0]==updated[1][0]==original[0][0]
    assert updated[0][1]==original[0][1]
    # New runtime records carry stronger direct ownership proof.
    axe['damage_callback']=dict(kind='EnemyAttackModule',owner_id=12)
    raw['label_schema']=5
    native,_=targets(raw,profile)
    assert len(native)==2
