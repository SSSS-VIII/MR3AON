"""Prefab references, hierarchy transforms and collision provenance, synthetic only."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_entity_catalog import Resources,trs,used_boards


def pointer(identity):
    return dict(m_FileID=0,m_PathID=identity)


def fixture(folder):
    folder.mkdir();asset='assets/enemy.prefab'
    objects={1:('AssetBundle',dict(m_Container=[[asset,dict(asset=pointer(10))],
                                              [asset,dict(asset=pointer(99))]],m_Dependencies=[])),
        10:('GameObject',dict(m_Name='Enemy',m_IsActive=True,m_Component=[dict(component=pointer(11))])),
        11:('Transform',dict(m_GameObject=pointer(10),m_LocalScale=dict(x=2,y=2,z=2),
                              m_LocalPosition=dict(x=1,y=2,z=0),m_Children=[pointer(21)])),
        20:('GameObject',dict(m_Name='Damage',m_IsActive=False,
                             m_Component=[dict(component=pointer(i))for i in (21,22)])),
        21:('Transform',dict(m_GameObject=pointer(20),m_LocalPosition=dict(x=3,y=0,z=0),m_Children=[])),
        22:('SphereCollider',dict(m_GameObject=pointer(20),m_Enabled=True,m_IsTrigger=True,m_Radius=.5)),
        99:('Mesh',dict(m_Name='Skeleton subasset'))}
    rows=[]
    for identity,(kind,value)in objects.items():
        file=f'{identity}.json';payload=json.dumps(value).encode();(folder/file).write_bytes(payload)
        rows.append(dict(bundle='root.ab',serialized_file='CAB-test',path_id=identity,type=kind,
                         type_tree=file,payload='original.bin',sha256=hashlib.sha256(payload).hexdigest()))
    (folder/'objects.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in rows))
    (folder/'recovery.json').write_text(json.dumps(dict(errors=[],bundles=[dict(name='root.ab')])) )
    return asset


def test_prefab_mesh_subasset_does_not_become_a_second_gameobject(tmp_path):
    folder=tmp_path/'resources';asset=fixture(folder);r=Resources([folder])
    assert len(r.containers[asset])==1
    data=r.prefab(asset)
    assert data['root']['path_id']==10 and len(data['colliders'])==1
    c=data['colliders'][0]
    assert c['enabled']and c['trigger']and not c['hierarchy_active']
    assert c['geometry']['m_Radius']==.5 and not c['runtime_verified']
    assert np.allclose(np.asarray(c['local_to_prefab'])[:3,3],[7,2,0])
    assert c['purpose']=='unverified_until_runtime'


def test_transform_rotation_and_nonuniform_scale_order():
    value=trs(dict(m_LocalRotation=dict(z=np.sqrt(.5),w=np.sqrt(.5)),m_LocalScale=dict(x=2,y=3,z=1)))
    assert value@np.asarray([1,0,0,1])==pytest.approx([0,2,0,1])
    with pytest.raises(ValueError,match='quaternion'):
        trs(dict(m_LocalRotation=dict(w=0)))


def test_dependency_cycles_are_preserved_and_missing_resources_fail(tmp_path):
    folder=tmp_path/'resources';fixture(folder);r=Resources([folder])
    r.bundles['shared.ab']={};r.dependencies={'root.ab':['shared.ab'],'shared.ab':['root.ab']}
    assert r.closure('root.ab')==['root.ab','shared.ab']
    r.dependencies['shared.ab'].append('absent.ab')
    with pytest.raises(ValueError,match='Unrecovered'):
        r.closure('root.ab')


def test_conflicting_versions_are_rejected_instead_of_merging_cab_ids(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';fixture(a);fixture(b)
    lines=[json.loads(x)for x in(b/'objects.jsonl').read_text().splitlines()]
    lines[0]['sha256']='changed_original'
    (b/'objects.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in lines))
    with pytest.raises(ValueError,match='Conflicting'):
        Resources([a,b])


def test_route_catalog_includes_opening_and_infinite_boards_without_duplicates():
    value=dict(maps={'1':dict(slots=[dict(pool=[dict(id=2),dict(id=3)])],
                              opening=[dict(pool=[dict(id=1)])],loop=[dict(id=3),dict(id=4)])})
    assert used_boards(value)=={1,2,3,4}
