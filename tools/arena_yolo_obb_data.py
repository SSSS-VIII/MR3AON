#!/usr/bin/env python3
"""Original resource/shape targets for the standard Ultralytics OBB trainer.

This prepares labels and a client resource profile, not a neural architecture.
Whole native episodes stay in their assigned split. Runtime labels never enter
the deployed visual actor.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from arena_native_json import normalize_arrays
from arena_projection import sphere_plane,capsule_plane
from arena_vision import Box

SHAPES=('BoxCollider','SphereCollider','CapsuleCollider')


def schema(entities,prefabs,reachable):
    indexed={e['type_id']:e for e in entities if e['kind']=='enemies'}
    families={};bindings={}
    for type_id in sorted(reachable):
        entity=indexed.get(type_id,{})
        resource=entity.get('resource_name')or f'type_{type_id}'
        family=families.setdefault(resource,dict(resource=resource,type_ids=[],shapes=set(),script_types=set(),
                                                configs={},prefabs=[],straight_bat=False))
        family['type_ids'].append(type_id);bindings[str(type_id)]=resource
        family['configs'][str(type_id)]=entity.get('config')
        for key in entity.get('prefabs',[]):
            prefab=prefabs[key];family['prefabs'].append(key)
            family['shapes'].update(c['component']for c in prefab['colliders']if c['component']in SHAPES)
            family['script_types'].update(s['class_name']for s in prefab['scripts'])
            family['straight_bat']|=any(s['class_name']=='EnemyStraightBat'for s in prefab['scripts'])
        if entity.get('config')is None:
            # Raw unresolved IDs are probed, never assigned a guessed prefab.
            family['shapes'].update(SHAPES)
    classes=[dict(name='player',kind='player',shape='CapsuleCollider')]
    for resource,family in sorted(families.items()):
        for shape in sorted(family['shapes']|{'cue'}):
            phases=('normal','ready','rush')if family['straight_bat']and shape!='cue'else('normal',)
            for phase in phases:
                classes.append(dict(name=resource+'__'+shape+'__'+phase,resource=resource,
                                    type_ids=family['type_ids'],shape=shape,phase=phase,
                                    kind='cue'if shape=='cue'else 'hazard'))
    for kind in ('rope','platform','floating_platform'):
        classes.append(dict(name=kind,kind=kind,shape='segment'))
    for family in families.values():
        family['shapes']=sorted(family['shapes']);family['script_types']=sorted(family['script_types'])
    return dict(version=1,task='obb',geometry='gameplay_plane',classes=classes,
                type_bindings=bindings,families=families,
                physics_targets='enabled nearest-owner Enemy tag; native layer retained (including fruit layer 17)',
                provenance='Original prefab/config ontology; unresolved raw IDs retain type_N labels')


def axis_quad(box):
    x1,y1,x2,y2=box
    return np.array([[x1,y1],[x2,y1],[x2,y2],[x1,y2]],np.float32)


def physics_profile(native):
    definitions=[('player','player','CapsuleCollider',None,None),
                 ('spider','hazard','SphereCollider','spider',None),
                 ('flying_normal','hazard','SphereCollider','eye_enemy','normal'),
                 ('pinball','hazard','SphereCollider','pinball',None),
                 ('box_hazard','hazard','BoxCollider','trap',None),
                 ('sphere_hazard','hazard','SphereCollider','trap',None),
                 ('flying_ready','hazard','SphereCollider','eye_enemy','ready'),
                 ('flying_rush','hazard','SphereCollider','eye_enemy','rush'),
                 ('capsule_hazard','hazard','CapsuleCollider','trap',None),
                 ('cue','cue','cue',None,None),('rope','rope','segment',None,None),
                 ('platform','platform','segment',None,None),('floating_platform','floating_platform','segment',None,None)]
    classes=[dict(name=n,kind=k,shape=s,motion_kind=m,phase=p,members=[])
             for n,k,s,m,p in definitions]
    mapping=[]
    for c in native['classes']:
        if c['kind']=='player':index=0
        elif c['kind']in('rope','platform','floating_platform'):
            index={'rope':10,'platform':11,'floating_platform':12}[c['kind']]
        elif c['shape']=='cue':index=9
        elif c['shape']=='BoxCollider':index=4
        elif c['shape']=='CapsuleCollider':index=8
        else:
            family=native['families'][c['resource']];scripts=family['script_types']
            if family['straight_bat']:index={'normal':2,'ready':6,'rush':7}[c['phase']]
            elif 'EnemyCurveBat'in scripts:index=2
            elif 'EnemySpider'in scripts:index=1
            elif 'EnemyPinball'in scripts:index=3
            else:index=5
        mapping.append(index);classes[index]['members'].append(c['name'])
    return dict(version=2,task='obb',geometry='gameplay_plane',taxonomy='physics',classes=classes,
                native_targets=native,class_mapping=mapping,families=native['families'],type_bindings=native['type_bindings'],
                provenance='Shared native collider/motion classes; original resources/configs remain in the profile')


def clipped_quad(quad):
    """Visible portion, converted by the same minAreaRect used by YOLO OBB."""
    points=np.asarray(quad,np.float32).reshape(-1,2)
    if len(points)!=4 or not np.isfinite(points).all():
        return None
    hull=cv2.convexHull(points)
    viewport=axis_quad([0,55,640,360]).reshape(-1,1,2)
    area,intersection=cv2.intersectConvexConvex(hull,viewport)
    if intersection is None or area<4:
        return None
    rect=cv2.minAreaRect(intersection)
    if min(rect[1])<1.5:
        return None
    # At a crop boundary the enclosing rectangle may extend slightly outside
    # the viewport; the standard dataset requires normalized corners in [0,1].
    return np.clip(cv2.boxPoints(rect),[0,0],[640,360]).astype(np.float32)


def collider_quad(collider):
    if collider.get('plane_quad'):
        return np.array([[p['x'],p['y']]for p in collider['plane_quad']],np.float32)
    if collider['type']=='BoxCollider':
        raise ValueError('A native BoxCollider plane quad is required')
    # Earlier schema4 captures retain the verified native 3-D AABB projection.
    # Recover its gameplay-plane section with the existing camera calibration.
    b=collider['box'];box=Box(b[0],b[1],b[2]-b[0],b[3]-b[1])
    plane=sphere_plane(box)if collider['type']=='SphereCollider'else capsule_plane(box)
    return axis_quad([plane.x,plane.y,plane.x+plane.w,plane.y+plane.h])


def segment_quad(a,b,thickness=4):
    delta=np.array([b['x']-a['x'],b['y']-a['y']],float)
    length=np.linalg.norm(delta)
    if length<4:return None
    normal=np.array([-delta[1],delta[0]])/length*thickness/2
    p=np.array([a['x'],a['y']]);q=np.array([b['x'],b['y']])
    return np.array([p-normal,q-normal,q+normal,p+normal],np.float32)


def object_resource(obj,profile):
    family_id=obj.get('family_type_id',obj.get('source_type_id'))
    resource=profile['type_bindings'].get(str(family_id))
    if resource is not None:return resource
    # Native FlyBamboo controller clones have EnemyInfo._enemyType == 0.
    # Resolve only an exact original prefab root AND matching original script;
    # never assign a meaning to zero, guess an unknown ID or use fuzzy names.
    name=obj.get('resource_family',obj.get('name','')).split('(Clone)',1)[0]
    family=profile['families'].get(name)
    if family and obj.get('type')in family['script_types']:
        return name
    return None


def targets(raw,profile):
    if profile.get('taxonomy')=='physics':
        native,counts=targets(raw,profile['native_targets'])
        return [(profile['class_mapping'][cls],quad)for cls,quad in native],counts
    row=normalize_arrays(raw)
    if row.get('label_schema',0)<4:
        raise ValueError('Full support supervision requires native label schema 4')
    keys={(c.get('resource'),c['shape'],c.get('phase','normal')):i for i,c in enumerate(profile['classes'])}
    support_ids={c['kind']:i for i,c in enumerate(profile['classes'])if c['shape']=='segment'}
    result=[];counts=Counter()
    def add(cls,quad):
        clipped=clipped_quad(quad)if quad is not None else None
        if clipped is not None:
            center=clipped.mean(0)
            if center[1]>275 and(center[0]<135 or center[0]>515):return
            result.append((cls,clipped.tolist()));counts['targets']+=1
    for collider in row['role']['colliders']or[]:add(0,collider_quad(collider))
    for obj in row.get('objects')or[]:
        if obj.get('dead')or not obj.get('renderers'):continue
        resource=object_resource(obj,profile)
        if resource is None:
            counts['unbound_family']+=1;continue
        physical=[]
        for collider in obj.get('colliders')or[]:
            if collider.get('owner_id')!=obj['id']:raise ValueError('Native collider ownership mismatch')
            if collider.get('tag')=='Enemy':physical.append(collider)
            else:counts['auxiliary_colliders']+=1
        phase='normal'
        if profile['families'][resource]['straight_bat']and physical:
            state=obj.get('controller',{}).get('_currState')
            if state is None:raise ValueError('Native straight-bat phase is required')
            phase={'ready':'ready','rushToNinja':'rush'}.get(state.split(':')[0],'normal')
        if physical:
            for collider in physical:
                key=(resource,collider['type'],phase)
                if key not in keys:
                    counts['unconfigured_shape']+=1;continue
                add(keys[key],collider_quad(collider))
        else:
            boxes=[r['box']for r in obj['renderers']]
            if boxes:
                a=np.asarray(boxes,float)
                add(keys[resource,'cue','normal'],axis_quad([*a[:,:2].min(0),*a[:,2:].max(0)]))
    for support in row.get('supports')or[]:
        if support.get('hidden')or support['kind']not in('rope','platform'):continue
        kind='floating_platform'if support.get('floating')else support['kind']
        add(support_ids[kind],segment_quad(support['start'],support['finish']))
    return result,counts


def build(output,train,validation,entities_path,prefabs_path,plan_path,physics=False):
    if {p.resolve()for p in train}&{p.resolve()for p in validation}:
        raise ValueError('Whole native episodes must be disjoint')
    def episode_keys(folders):
        return {(s['seed'],s['level'],s['map'])for s in
                (json.loads((folder/'setup.json').read_text())for folder in folders)}
    if episode_keys(train)&episode_keys(validation):
        raise ValueError('A native map seed cannot cross dataset splits')
    plan=json.loads(plan_path.read_text())
    if plan.get('mode')!=6:raise ValueError('Only Gale resource pools may enter this dataset')
    profile=schema(json.loads(entities_path.read_text()),json.loads(prefabs_path.read_text()),plan['reachable_enemy_types'])
    if physics:profile=physics_profile(profile)
    output.mkdir(parents=True,exist_ok=False)
    runtime_names=defaultdict(set);runtime_types=defaultdict(set)
    manifest=dict(task='standard Ultralytics YOLO26 OBB',profile='profile.json',splits={},sources={},
                  source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in(entities_path,prefabs_path,plan_path,Path(__file__))})
    for split,folders in [('train',train),('val',validation)]:
        (output/'images'/split).mkdir(parents=True);(output/'labels'/split).mkdir(parents=True)
        counts=Counter();per_class=Counter()
        for folder in folders:
            labels_file=folder/'labels.jsonl'
            manifest['sources'][str(folder)]=dict(split=split,sha256=hashlib.sha256(labels_file.read_bytes()).hexdigest())
            for line in labels_file.open():
                row=normalize_arrays(json.loads(line));labels,stats=targets(row,profile);counts.update(stats);counts['frames']+=1
                if split=='train':
                    for obj in row.get('objects')or[]:
                        resource=object_resource(obj,profile)
                        if resource:
                            runtime_names[resource].add(obj.get('resource_family',obj['name']).split('(Clone)',1)[0])
                            runtime_types[resource].add(obj['type'])
                name=folder.name+'-'+row['image']
                (output/'images'/split/name).symlink_to((folder/row['image']).resolve())
                text=[]
                for cls,quad in labels:
                    coordinates=np.asarray(quad)/[640,360];per_class[str(cls)]+=1
                    text.append(str(cls)+' '+' '.join(f'{v:.7f}'for v in coordinates.ravel())+'\n')
                (output/'labels'/split/Path(name).with_suffix('.txt')).write_text(''.join(text))
        manifest['splits'][split]=dict(counts=counts,class_targets=per_class)
    for resource,family in profile['families'].items():
        family['observed_training_names']=sorted(runtime_names[resource])
        family['observed_training_types']=sorted(runtime_types[resource])
    (output/'profile.json').write_text(json.dumps(profile,indent=2)+'\n')
    config=dict(path=str(output.resolve()),train='images/train',val='images/val',names=[c['name']for c in profile['classes']])
    (output/'data.yaml').write_text(json.dumps(config,indent=2)+'\n')
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in('output','entities','prefabs','plan'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--train',type=Path,nargs='+',required=True);p.add_argument('--validation',type=Path,nargs='+',required=True)
    p.add_argument('--physics',action='store_true',help='Share classes by original collider and motion family, retaining the full resource profile')
    a=p.parse_args();result=build(a.output,a.train,a.validation,a.entities,a.prefabs,a.plan,a.physics)
    print(json.dumps(result['splits']),flush=True)
