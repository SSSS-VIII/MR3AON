"""Native phase supervision must not guess states absent from old captures."""
import json
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_yolo_obb_data import schema,physics_profile,targets,MissingBambooPhase,build


def ontology():
    return ([dict(kind='enemies',type_id=102,resource_name='EnemyFlyBamboo',config={},prefabs=['p'])],
            dict(p=dict(colliders=[dict(component='BoxCollider')],scripts=[dict(class_name='EnemyFlyBamboo')])))


def frame(state,x=550):
    controller={}if state is None else dict(_enemyState=state)
    return dict(label_schema=4,image='000000.png',role=dict(colliders=[]),supports=[],objects=[dict(
        id=1,name='EnemyFlyBamboo(Clone)',type='EnemyFlyBamboo',family_type_id=102,
        renderers=[dict(name='Sprite',box=[x-200,170,x-170,200])],controller=controller,colliders=[dict(
            type='BoxCollider',owner_id=1,tag='Enemy',box=[x,180,x+70,188],layer=9,
            plane_quad=[dict(x=a,y=b)for a,b in ((x,180),(x+70,180),(x+70,188),(x,188))])])])


@pytest.mark.parametrize('state,expected',[('aim: 0','aim'),('none: 5','aim'),
    ('aimLock: 1','locked'),('readyAttack: 2','locked'),('flyToNinja: 3','attack'),('insertEdge: 4','attack')])
def test_exact_original_phase_separates_identical_physical_quads(state,expected):
    entities,prefabs=ontology();p=physics_profile(schema(entities,prefabs,[102],bamboo_phases=True))
    labels,_=targets(frame(state),p)
    assert [p['classes'][c]['name']for c,q in labels]==(['bamboo_attack']if expected=='attack'else['bamboo_'+expected,'box_hazard'])
    assert p['classes'][labels[0][0]]['motion_kind']=='bamboo'
    if expected!='attack':
        assert max(point[0]for point in labels[0][1])<400
        assert min(point[0]for point in labels[1][1])>500


def test_old_bamboo_phase_is_unknown_instead_of_assumed_aim():
    entities,prefabs=ontology();p=schema(entities,prefabs,[102],bamboo_phases=True)
    with pytest.raises(MissingBambooPhase):targets(frame(None),p)
    with pytest.raises(MissingBambooPhase):targets(frame(None,x=700),p)  # Marker still visible.
    assert targets(frame(None,x=900),p)[0]==[]
    with pytest.raises(ValueError,match='Unreviewed'):targets(frame('futureNewState: 6'),p)
    # Existing default models retain their old, explicit shared-shape taxonomy.
    old=physics_profile(schema(entities,prefabs,[102]))
    assert old['classes'][targets(frame(None),old)[0][0][0]]['name']=='box_hazard'


def test_old_missing_phase_omits_whole_image_without_training_false_background(tmp_path):
    entities,prefabs=ontology()
    files=[]
    for name,value in [('entities',entities),('prefabs',prefabs),('plan',dict(mode=6,reachable_enemy_types=[102]))]:
        path=tmp_path/name;path.write_text(json.dumps(value));files.append(path)
    episodes=[]
    for seed,state in [(1,None),(2,'aim: 0')]:
        folder=tmp_path/f'episode-{seed}';folder.mkdir();episodes.append(folder)
        (folder/'setup.json').write_text(json.dumps(dict(seed=seed,level=5,map=41)))
        (folder/'labels.jsonl').write_text(json.dumps(frame(state))+'\n')
        (folder/'000000.png').write_bytes(b'not read by label builder')
    out=tmp_path/'data'
    manifest=build(out,episodes[:1],episodes[1:],*files,physics=True,bamboo_phases=True)
    assert manifest['splits']['train']['counts']['excluded_missing_bamboo_phase_frames']==1
    assert not list((out/'images/train').iterdir())
    assert len(list((out/'images/val').iterdir()))==1
