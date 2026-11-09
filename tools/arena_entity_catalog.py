#!/usr/bin/env python3
"""Join original Gale placements, prefab hierarchies and serialized colliders.

No account/device access. Outputs original client data into private debug paths.
Serialized collider parameters are not asserted to be live damage geometry.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def trs(tree):
    def xyz(key,default):
        return [tree.get(key,{}).get(axis,default)for axis in ('x','y','z')]
    x,y,z,w=[tree.get('m_LocalRotation',{}).get(k,1 if k=='w'else 0)for k in ('x','y','z','w')]
    norm=x*x+y*y+z*z+w*w
    if abs(norm-1)>1e-3:
        raise ValueError('Non-unit original transform quaternion')
    rotation=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                       [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                       [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
    result=np.eye(4);result[:3,:3]=rotation@np.diag(xyz('m_LocalScale',1))
    result[:3,3]=xyz('m_LocalPosition',0)
    return result


class Resources:
    def __init__(self,folders):
        self.rows={};self.containers=defaultdict(list);self.externals={};self.trees={}
        self.bundles={};self.dependencies={};self.exports=[]
        for folder in folders:
            report=json.loads((folder/'recovery.json').read_text())
            if report['errors']:
                raise ValueError(f'Unsuccessful original export: {folder}')
            self.exports.append(dict(folder=str(folder),patch_version=report.get('patch_version_bytes_hex'),
                                     sha256=hashlib.sha256((folder/'recovery.json').read_bytes()).hexdigest()))
            for bundle in report['bundles']:
                self.bundles[bundle['name']]=bundle
            for line in (folder/'objects.jsonl').open():
                row=json.loads(line)
                key=(row['serialized_file'].lower(),row['path_id'])
                if key in self.rows and self.rows[key]['sha256']!=row['sha256']:
                    raise ValueError(f'Conflicting original object {key}')
                self.rows[key]=dict(row,base=folder)
        versions={e['patch_version']for e in self.exports if e['patch_version']is not None}
        if len(versions)>1 or versions and any(e['patch_version']is None for e in self.exports):
            raise ValueError('Original resource exports have incompatible or unknown patch versions')
        for key,row in self.rows.items():
            if row['type']=='AssetBundle':
                self.dependencies[row['bundle']]=self.tree(row).get('m_Dependencies',[])
                for asset,entry in self.tree(row).get('m_Container',[]):
                    # Unity lists mesh/subassets under the same .prefab path.
                    # Only a GameObject is an instantiable prefab root.
                    target=self.resolve(row,entry['asset'])
                    if asset.lower().endswith('.prefab')and (target is None or target['type']!='GameObject'):
                        continue
                    self.containers[asset.lower()].append((row,entry['asset']))

    def tree(self,row):
        key=(row['serialized_file'],row['path_id'])
        if key not in self.trees:
            self.trees[key]=json.loads((row['base']/row['type_tree']).read_text())
        return self.trees[key]

    def resolve(self,owner,pointer):
        identity=pointer.get('m_PathID',0)
        if not identity:
            return None
        filename=owner['serialized_file'].lower();index=pointer.get('m_FileID',0)
        if index:
            if filename not in self.externals:
                import UnityPy
                env=UnityPy.load(str(owner['base']/'serialized'/owner['serialized_file']))
                asset=next(v for v in env.files.values()if hasattr(v,'externals'))
                self.externals[filename]=[Path(e.path.replace('\\','/')).name.lower()for e in asset.externals]
            names=self.externals[filename]
            if not 1<=index<=len(names):
                return None
            filename=names[index-1]
        return self.rows.get((filename,identity))

    def evidence(self,row):
        return dict(bundle=row['bundle'],file=row['serialized_file'],path_id=row['path_id'],
                    type=row['type'],sha256=row['sha256'],type_tree=str(row['base']/row['type_tree']))

    def closure(self,bundle):
        seen=set();todo=[bundle]
        while todo:
            name=todo.pop()
            if name in seen:
                continue
            if name not in self.bundles:
                raise ValueError(f'Unrecovered prefab dependency: {name}')
            seen.add(name);todo.extend(self.dependencies.get(name,[]))
        return sorted(seen)

    def prefab(self,asset,bundle=None,root_id=None):
        sources=self.containers.get(asset.lower(),[])
        if bundle is not None:
            sources=[(r,p)for r,p in sources if r['bundle']==bundle]
        if root_id is not None:
            sources=[(r,p)for r,p in sources if p['m_PathID']==root_id]
        unique={(r['serialized_file'],p['m_FileID'],p['m_PathID']):(r,p)for r,p in sources}
        if len(unique)!=1:
            raise ValueError(f'Prefab must resolve uniquely: {asset} ({len(unique)})')
        owner,pointer=next(iter(unique.values()));root=self.resolve(owner,pointer)
        if root is None or root['type']!='GameObject':
            raise ValueError(f'Unresolved original prefab root: {asset}')
        nodes=[];colliders=[];scripts=[];renderers=[];seen=set()
        def walk(go,parent,path,chain_active):
            identity=(go['serialized_file'],go['path_id'])
            if identity in seen:
                raise ValueError(f'Cycle in prefab transform hierarchy: {asset}')
            seen.add(identity)
            tree=self.tree(go);name=tree['m_Name'];full=path+'/'+name
            active=chain_active and bool(tree.get('m_IsActive',True))
            components=[];transform=None
            for entry in tree['m_Component']:
                row=self.resolve(go,entry['component'])
                if row is None:
                    raise ValueError(f'Unresolved prefab component: {asset} {full}')
                components.append(row)
                if row['type']in ('Transform','RectTransform'):
                    transform=row
            if transform is None:
                raise ValueError('GameObject lacks transform')
            transform_tree=self.tree(transform);matrix=parent@trs(transform_tree)
            nodes.append(dict(path=full,active=active,transform=transform_tree,
                              local_to_prefab=matrix.tolist(),source=self.evidence(go)))
            for row in components:
                data=self.tree(row)
                if 'Collider' in row['type']:
                    colliders.append(dict(path=full,component=row['type'],enabled=bool(data.get('m_Enabled',True)),
                        hierarchy_active=active,trigger=bool(data.get('m_IsTrigger',False)),
                        geometry=data,local_to_prefab=matrix.tolist(),source=self.evidence(row),
                        purpose='unverified_until_runtime',runtime_verified=False))
                elif row['type']=='MonoBehaviour':
                    script=self.resolve(row,data.get('m_Script',{}))
                    classname=self.tree(script).get('m_ClassName')if script else None
                    scripts.append(dict(path=full,class_name=classname,enabled=data.get('m_Enabled'),
                                        source=self.evidence(row)))
                elif row['type']in ('SpriteRenderer','MeshRenderer','SkinnedMeshRenderer','MeshFilter',
                                    'ParticleSystemRenderer','Animator','Animation'):
                    renderers.append(dict(path=full,component=row['type'],hierarchy_active=active,
                                          enabled=data.get('m_Enabled'),source=self.evidence(row)))
            for pointer in transform_tree.get('m_Children',[]):
                child=self.resolve(transform,pointer)
                if child is None:
                    raise ValueError(f'Unresolved child transform: {asset}')
                child_go=self.resolve(child,self.tree(child)['m_GameObject'])
                if child_go is None:
                    raise ValueError('Unresolved child GameObject')
                walk(child_go,matrix,full,active)
        walk(root,np.eye(4),'',True)
        return dict(asset=asset,root=self.evidence(root),nodes=nodes,colliders=colliders,scripts=scripts,
                    render_components=renderers,dependency_bundles=self.closure(root['bundle']),
                    collision_status='serialized_only'if colliders else'no_serialized_collider',
                    runtime_verified=False)


def used_boards(catalog):
    ids=set()
    for value in catalog['maps'].values():
        for slot in value.get('slots',[])+value.get('opening',[]):
            ids.update(c['id']for c in slot['pool'])
        ids.update(c['id']for c in value.get('loop',[]))
    return ids


def build(base,output,resources):
    output.mkdir(parents=True,exist_ok=False)
    plan=json.loads((base/'decoded/arena-resource-plan-complete-index.json').read_text())
    routes=json.loads((base/'gameonly/gale-catalog-native.json').read_text())
    ids=used_boards(routes);usage=defaultdict(lambda:dict(count=0,stages=set()))
    grounds=Counter();found=set();blocks=0
    with (output/'placements.jsonl').open('w')as placements,(output/'terrain-layouts.jsonl').open('w')as terrain:
        for path in sorted((base/'dataset/assets').rglob('stage_endless_gale_*.json')):
            stage=json.loads(path.read_text());identity=stage['_stageID']
            if identity not in ids:
                continue
            found.add(identity)
            if stage['_levelDataType']!=6:
                raise ValueError('Non-Gale data in original route')
            for gi,group in enumerate(stage['_levelBlockInfos']):
                for bi,block in enumerate(group):
                    blocks+=1;grounds[str(block.get('_groundType','omitted'))]+=1
                    geometry={k:v for k,v in block.items()if k not in ('enemyInfos','itemInfos','npcInfos')}
                    terrain.write(json.dumps(dict(stage=identity,group=gi,block=bi,geometry=geometry))+'\n')
                    for kind,listkey,key in [('enemies','enemyInfos','_enemyType'),('items','itemInfos','_itemType')]:
                        for index,entry in enumerate(block.get(listkey,[])):
                            t=entry[key];u=usage[kind,t];u['count']+=1;u['stages'].add(identity)
                            placements.write(json.dumps(dict(kind=kind,type_id=t,stage=identity,
                                group=gi,block=bi,index=index,placement=entry))+'\n')
    if ids-found:
        raise ValueError(f'Missing original route stages: {sorted(ids-found)}')
    entities=[];prefabs={};missing=[]
    for entry in plan['resolved']+plan['missing']:
        kind,t=entry['kind'],entry['type_id'];u=usage.get((kind,t),dict(count=0,stages=set()))
        entity=dict(kind=kind,type_id=t,resource_name=entry.get('resource_name'),config=entry.get('config'),
                    gale_usage=dict(placements=u['count'],stages=sorted(u['stages'])),prefabs=[],
                    detector_status='not_configured',runtime_verified=False)
        if entry.get('config')is None:
            entity['status']='missing_current_config';missing.append(dict(kind=kind,type_id=t,gale_placements=u['count']))
        else:
            suffix='/'+entry['resource_name'].lower()+'.prefab'
            assets=[a for a in resources.containers if a.endswith(suffix)]
            # The original plan identifies the bundle when multiple aliases exist.
            assets=[a for a in assets if any(row['bundle']in entry['bundles']for row,_ in resources.containers[a])]
            if len(assets)!=1:
                raise ValueError(f'Entity prefab not unique: {kind}/{t}: {assets}')
            for asset in assets:
                sources={(row['bundle'],pointer['m_PathID'])for row,pointer in resources.containers[asset]
                         if row['bundle']in entry['bundles']}
                for bundle,root_id in sorted(sources):
                    key=bundle+'::'+asset+'#'+str(root_id)
                    if key not in prefabs:
                        prefabs[key]=resources.prefab(asset,bundle,root_id)
                    entity['prefabs'].append(key)
            entity['status']='resources_indexed'
        entities.append(entity)
    indexed={(e['kind'],e['type_id'])for e in entities}
    if set(usage)-indexed:
        raise ValueError(f'Gale entities absent from original resource plan: {set(usage)-indexed}')
    for asset in sorted(resources.containers):
        if asset.endswith('.prefab')and ('/theme/ground/'in asset or '/combatobj/item/prefab/common/line'in asset):
            for bundle,root_id in sorted({(row['bundle'],pointer['m_PathID'])for row,pointer in resources.containers[asset]}):
                prefabs[bundle+'::'+asset+'#'+str(root_id)]=resources.prefab(asset,bundle,root_id)
    with (output/'visual-resources.jsonl').open('w')as stream:
        for row in resources.rows.values():
            if row['type']in ('Texture2D','Sprite','Mesh','Material','Shader','TextAsset',
                              'AnimationClip','AnimatorController','ParticleSystem'):
                value=resources.evidence(row);value.update(name=row.get('name'),payload=str(row['base']/row['payload']))
                if row.get('text_asset'):
                    value['text_asset']=str(row['base']/row['text_asset'])
                if row['type']=='Texture2D':
                    value['texture_previews']=[str(p)for p in(row['base']/'texture-previews').glob(str(row['path_id'])+'-*')]
                    value['preview_kind']='texture_or_atlas_not_rendered_object'
                stream.write(json.dumps(value,ensure_ascii=False)+'\n')
    detector_classes=[]
    for entity in entities:
        if not entity['gale_usage']['placements']:
            continue
        detector_classes.append(dict(key=f'{entity["kind"]}:{entity["type_id"]}',resource_name=entity['resource_name'],
            prefabs=entity['prefabs'],renderable=any(prefabs[k]['render_components']for k in entity['prefabs']),
            reference_examples=[],status='pending_visual_examples'if entity['prefabs']else'missing_current_config'))
    summary=dict(schema=1,status='resource_catalog_not_detector_acceptance',source_exports=resources.exports,
        route_stage_ids=len(found),
        block_alternatives=blocks,ground_types=dict(grounds),gale_enemy_types=sum(k=='enemies'for k,t in usage),
        gale_item_types=sum(k=='items'for k,t in usage),entities=len(entities),prefabs=len(prefabs),
        colliders=sum(len(p['colliders'])for p in prefabs.values()),missing=missing,
        runtime_verified=False,notes=['Collider geometry is local serialized data with full parent TRS.',
        'No damage-purpose or live animation-state equivalence has been inferred.',
        'Ground/rope library includes shared themes; placements include Gale routes only.'])
    for name,value in [('entities.json',entities),('prefabs.json',prefabs),('summary.json',summary),
                       ('detector-classes.json',detector_classes)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,default=ROOT/'debug/arena-client')
    p.add_argument('--resources',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.base,a.output,Resources(a.resources)),ensure_ascii=False))


if __name__=='__main__':
    main()
