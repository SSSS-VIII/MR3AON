#!/usr/bin/env python3
"""Export source-proven EnemyAttackModule collider bindings for annotation.

This is offline client metadata. It must never become a live actor input.
Unknown references remain explicit instead of turning every untagged trigger
into a damage collider.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_TREES=ROOT/'debug/arena-client/arena-entities-complete/type-trees'
COLLIDERS=('BoxCollider','SphereCollider','CapsuleCollider')


def pointer(value):
    if not isinstance(value,dict)or value.get('m_FileID')!=0:return None
    value=value.get('m_PathID')
    return value if type(value)is int and value!=0 else None


def build_registry(root):
    root=Path(root);bindings=[];unresolved=[];source_hashes={};proof_paths=set();scanned=0
    def read(path):
        payload=path.read_bytes()
        source_hashes[path.relative_to(root).as_posix()]=hashlib.sha256(payload).hexdigest()
        return json.loads(payload)
    for bundle in sorted(p for p in root.iterdir()if p.is_dir()):
        scanned+=1;scripts={};script_paths={}
        for path in sorted(bundle.glob('*.MonoScript.json')):
            data=read(path);identity=int(path.name.split('.')[0]);scripts[identity]=data.get('m_ClassName');script_paths[identity]=path.name
        module_scripts={k for k,v in scripts.items()if v=='EnemyAttackModule'}
        if not module_scripts:continue
        components={};component_paths={}
        for path in sorted(bundle.glob('*.MonoBehaviour.json')):
            identity=int(path.name.split('.')[0]);components[identity]=read(path);component_paths[identity]=path.name
        colliders={};go={};transforms={};transform_for_go={}
        for kind in (*COLLIDERS,'GameObject','Transform'):
            for path in sorted(bundle.glob('*.'+kind+'.json')):
                identity=int(path.name.split('.')[0]);data=read(path)
                if kind=='GameObject':go[identity]=data
                elif kind=='Transform':
                    transforms[identity]=data;transform_for_go[pointer(data.get('m_GameObject'))]=identity
                else:colliders[identity]=(kind,data,path.name)
        for identity,module in sorted(components.items()):
            script=pointer(module.get('m_Script'))
            if script not in module_scripts:continue
            proof=dict(bundle=bundle.name,module_component=identity,module_source=component_paths[identity],
                       script_source=script_paths[script])
            owner_id=pointer(module.get('_belongToEnemy'));owner=components.get(owner_id)
            collider_go=pointer(module.get('m_GameObject'));gameobject=go.get(collider_go)
            if owner is None or gameobject is None:
                unresolved.append(dict(**proof,reason='nonlocal_or_missing_owner_or_gameobject'));continue
            owner_class=scripts.get(pointer(owner.get('m_Script')))
            owner_go=pointer(owner.get('m_GameObject'));owner_object=go.get(owner_go)
            if not owner_class or owner_object is None:
                unresolved.append(dict(**proof,reason='nonlocal_or_missing_owner_script'));continue
            candidates=[]
            for entry in gameobject.get('m_Component',[]):
                candidate=pointer(entry.get('component'))
                if candidate in colliders:candidates.append(candidate)
            if not candidates:
                unresolved.append(dict(**proof,reason='module_without_supported_collider'));continue
            parents=set();transform=transform_for_go.get(collider_go)
            while transform is not None and transform not in parents:
                parents.add(transform);data=transforms.get(transform)
                if not data:break
                transform=pointer(data.get('m_Father'))
            owner_ancestor=transform_for_go.get(owner_go)in parents
            for candidate in candidates:
                kind,collider,path=colliders[candidate]
                signature={key:collider[source]for key,source in
                           [('center','m_Center'),('size','m_Size'),('radius','m_Radius'),
                            ('height','m_Height'),('direction','m_Direction')]
                           if source in collider}
                used=[script_paths[script],component_paths[identity],component_paths[owner_id],
                      script_paths[pointer(owner.get('m_Script'))],path,
                      str(collider_go)+'.GameObject.json',str(owner_go)+'.GameObject.json']
                used.extend(str(t)+'.Transform.json'for t in parents if t in transforms)
                proof_paths.update(bundle.name+'/'+name for name in used)
                bindings.append(dict(**proof,owner_component=owner_id,owner_source=component_paths[owner_id],
                    owner_class=owner_class,owner_name=owner_object.get('m_Name'),
                    collider_component=candidate,collider_source=path,collider_name=gameobject.get('m_Name'),
                    collider_type=kind,tag_id=gameobject.get('m_Tag'),
                    enabled_in_prefab=bool(collider.get('m_Enabled')),is_trigger=bool(collider.get('m_IsTrigger')),
                    owner_in_ancestors=owner_ancestor,signature=signature))
    bindings.sort(key=lambda b:(b['bundle'],b['module_component'],b['collider_component']))
    return dict(schema=1,scope='Original EnemyAttackModule._belongToEnemy component references; offline annotation only.',
        bindings=bindings,unresolved=unresolved,
        input_files_read=len(source_hashes),
        inputs_digest_sha256=hashlib.sha256(json.dumps(source_hashes,sort_keys=True).encode()).hexdigest(),
        source_sha256={k:source_hashes[k]for k in sorted(proof_paths)},
        counts=dict(bundles_scanned=scanned,bindings=len(bindings),
                    owners=len({(b['bundle'],b['owner_component'])for b in bindings}),
                    owner_classes=sorted({b['owner_class']for b in bindings}),
                    untagged_bindings=sum(b['tag_id']==0 for b in bindings),
                    detached_bindings=sum(not b['owner_in_ancestors']for b in bindings),unresolved=len(unresolved)))


def attach_damage_modules(profile,registry):
    """Explicitly version old-label retrofits; frozen profiles stay unchanged."""
    if registry.get('schema')!=1:raise ValueError('Unsupported damage module registry')
    result=deepcopy(profile)
    result['physics_targets']='enabled nearest-owner Enemy tag or verified EnemyAttackModule callback; source retrofit explicit'
    if result.get('taxonomy')=='physics':
        result['native_targets']=attach_damage_modules(result['native_targets'],registry)
    else:
        result['source_damage_modules']=deepcopy(registry['bindings'])
    payload=json.dumps(registry,sort_keys=True,separators=(',',':')).encode()
    result['damage_modules_sha256']=hashlib.sha256(payload).hexdigest()
    return result


def separate_damage_modules(profile,registry):
    """Give verified weapons their own stock-YOLO classes, retaining old IDs.

    A weapon and its enemy body may share the Enemy tag taxonomy but have very
    different motion. This is an explicit new profile, never an old-profile
    reinterpretation. Unreachable prefab bindings remain recorded as skipped.
    """
    if profile.get('taxonomy')!='physics':raise ValueError('Expected a physics profile')
    if profile.get('separate_damage_modules'):raise ValueError('Damage modules already separated')
    result=attach_damage_modules(profile,registry);native=result['native_targets']
    if len(result['class_mapping'])!=len(native['classes']):
        raise ValueError('Native class mapping is inconsistent')
    grouped={};skipped=[]
    for binding in registry['bindings']:
        resource=binding['owner_name'];shape=binding['collider_type']
        if resource not in native['families']:
            skipped.append(dict(resource=resource,reason='not_in_frozen_profile'));continue
        key=(binding['owner_class'],shape)
        grouped.setdefault(key,set()).add(resource)
    additions=[]
    for (owner_class,shape),resources in sorted(grouped.items()):
        class_id=len(result['classes']);members=[]
        for resource in sorted(resources):
            original=[c for c in native['classes']if c.get('resource')==resource
                      and c['shape']==shape and c.get('phase','normal')=='normal']
            if len(original)!=1:raise ValueError('Missing or ambiguous source body class: '+resource)
            name=resource+'__'+shape+'__attack_module'
            native['classes'].append(dict(deepcopy(original[0]),name=name,
                phase='attack_module',source_damage_callback='EnemyAttackModule'))
            native['families'][resource].setdefault('damage_module_phases',{})[shape]='attack_module'
            result['class_mapping'].append(class_id);members.append(name)
        entry=dict(name=owner_class+'__attack_module__'+shape,kind='hazard',shape=shape,
                   motion_kind='trap',phase=None,members=members,source_owner_class=owner_class,
                   source_damage_callback='EnemyAttackModule')
        if len(resources)==1:entry['resource']=next(iter(resources))
        result['classes'].append(entry);additions.append(dict(class_id=class_id,**entry))
    if not additions:raise ValueError('No source damage modules reachable in this profile')
    result['families']=deepcopy(native['families'])
    result['separate_damage_modules']=dict(classes=additions,skipped=skipped,
        scope='Explicit stock head class extension; old class IDs and all physical geometry retained')
    return result


def _same_geometry(observed,expected):
    if isinstance(expected,dict):
        return isinstance(observed,dict)and all(k in observed and _same_geometry(observed[k],v)
                                              for k,v in expected.items())
    if isinstance(expected,(int,float))and not isinstance(expected,bool):
        return (isinstance(observed,(int,float))and not isinstance(observed,bool)
                and math.isfinite(observed)and math.isclose(observed,expected,rel_tol=1e-6,abs_tol=1e-6))
    return observed==expected


def is_attack_module_collider(obj,collider,bindings=()):
    """Identify the original module independently of its object's tag."""
    if collider.get('owner_id')!=obj.get('id'):raise ValueError('Native collider ownership mismatch')
    callback=collider.get('damage_callback')
    if callback is not None and not isinstance(callback,dict):raise ValueError('Invalid damage callback metadata')
    if callback and callback.get('kind')=='EnemyAttackModule':
        if callback.get('owner_id')!=obj['id']:raise ValueError('Damage callback ownership mismatch')
        return True
    # Old frames have no callback field. Require the whole source signature,
    # including the native owner and collider object name; no shape guessing.
    name=obj.get('name','').replace('(Clone)','')
    for binding in bindings:
        required={'BoxCollider':('center','size'),'SphereCollider':('center','radius'),
                  'CapsuleCollider':('center','radius','height','direction')}.get(binding.get('collider_type'),())
        signature=binding.get('signature',{})
        if not required or any(key not in signature for key in required):continue
        if (binding.get('owner_class')==obj.get('type')and binding.get('owner_name')==name
                and binding.get('collider_name')==collider.get('name')
                and binding.get('collider_type')==collider.get('type')
                and collider.get('tag')=='Untagged'and binding.get('tag_id')==0
                and all(key in collider and _same_geometry(collider[key],value)
                        for key,value in binding['signature'].items())):
            return True
    return False


def is_damage_collider(obj,collider,bindings=()):
    """Accept Enemy tag, a verified runtime handler, or an exact source binding."""
    return is_attack_module_collider(obj,collider,bindings)or collider.get('tag')=='Enemy'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--type-trees',type=Path,default=DEFAULT_TREES)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=build_registry(args.type_trees)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x')as stream:json.dump(result,stream,indent=2,ensure_ascii=False);stream.write('\n')
    print(json.dumps(result['counts'],ensure_ascii=False))


if __name__=='__main__':main()
