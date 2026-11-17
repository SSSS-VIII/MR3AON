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
from arena_damage_modules import is_damage_collider,is_attack_module_collider

SHAPES=('BoxCollider','SphereCollider','CapsuleCollider')
INTERACTIONS=Path(__file__).resolve().parents[1]/'arena/vision-interactions.json'


class MissingBambooPhase(ValueError):
    """Old paired labels cannot supervise a native state they did not record."""


def schema(entities,prefabs,reachable,bamboo_phases=False,arrow_family=False,mace_family=False):
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
    for entity in entities:
        if entity['kind']!='runtime_enemies':continue
        resource=entity['resource_name']
        if resource in families:continue
        family=dict(resource=resource,type_ids=[],source_type_id=0,shapes=set(),script_types=set(),configs={},
                    prefabs=list(entity['prefabs']),straight_bat=False,native_zero_source=True)
        for key in entity['prefabs']:
            prefab=prefabs[key]
            family['shapes'].update(c['component']for c in prefab['colliders']if c['component']in SHAPES)
            family['script_types'].update(s['class_name']for s in prefab['scripts'])
            family['straight_bat']|=any(s['class_name']=='EnemyStraightBat'for s in prefab['scripts'])
        families[resource]=family
    classes=[dict(name='player',kind='player',shape='CapsuleCollider')]
    for resource,family in sorted(families.items()):
        if bamboo_phases and resource=='EnemyFlyBamboo':family['bamboo_phases']=True
        if arrow_family and resource=='EnemyArrow':
            if 'EnemyArrow'not in family['script_types']or family['shapes']!={'BoxCollider'}:
                raise ValueError('Original EnemyArrow script/collider differs from the reviewed family')
            family['arrow_family']=True
        if mace_family and resource in('EnemyMace','EnemyGoldMace'):
            if 'EnemyMace'not in family['script_types']or family['shapes']!={'BoxCollider'}:
                raise ValueError('Original EnemyMace script/collider differs from the reviewed family')
            geometries=[]
            for key in family['prefabs']:
                boxes=[c for c in prefabs[key]['colliders']if c['component']=='BoxCollider']
                if len(boxes)!=1 or not np.allclose(boxes[0]['local_to_prefab'],np.eye(4),atol=1e-7):
                    raise ValueError('Original EnemyMace root collider transform differs')
                shape=boxes[0]['geometry'];size=shape['m_Size'];center=shape['m_Center']
                if not np.allclose([size['x'],size['y'],center['x'],center['y']],[.45,1.9,0.,1.4],atol=1e-6):
                    raise ValueError('Original EnemyMace eccentric geometry differs')
                geometries.append(dict(short_side=size['x'],long_side=size['y'],center_long=center['y']))
            if not geometries:raise ValueError('Original EnemyMace root geometry is missing')
            family['mace_geometry']=geometries[0]
        for shape in sorted(family['shapes']|{'cue'}):
            phases=(('normal','attack')if family.get('bamboo_phases')else
                    ('normal','ready','rush')if family['straight_bat']else('normal',))if shape!='cue'else('normal',)
            for phase in phases:
                classes.append(dict(name=resource+'__'+shape+'__'+phase,resource=resource,
                                    type_ids=family['type_ids'],shape=shape,phase=phase,
                                    kind='cue'if shape=='cue'else 'hazard'))
        if family.get('bamboo_phases'):
            for phase in ('aim','locked'):
                classes.append(dict(name=resource+'__cue__'+phase,resource=resource,
                    type_ids=family['type_ids'],shape='cue',phase=phase,kind='cue'))
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


def physics_profile(native,interactions=False):
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
    rules=json.loads(INTERACTIONS.read_text())if interactions else None
    if interactions:
        definitions.extend([('fruit_box','slice_target','BoxCollider','slice_target',None),
                            ('fruit_capsule','slice_target','CapsuleCollider','slice_target',None),
                            ('muppet_bomb','hazard','SphereCollider','spider',None)])
        for resource,rule in rules['resources'].items():
            family=native['families'].get(resource)
            if family is None:continue
            config=family['configs'].get(str(rule['type_id']))
            if (rule['script']not in family['script_types']or config is None
                    or any(config.get(k)!=rule[k]for k in ('damage','species'))):
                raise ValueError(f'Original interaction CFG/script differs from reviewed evidence: {resource}')
    if native['families'].get('EnemyFlyBamboo',{}).get('bamboo_phases'):
        definitions.extend([('bamboo_'+phase,'cue','cue','bamboo',phase)for phase in ('aim','locked')])
        definitions.append(('bamboo_attack','hazard','BoxCollider','bamboo','attack'))
    if native['families'].get('EnemyArrow',{}).get('arrow_family'):
        definitions.append(('arrow','hazard','BoxCollider','arrow',None))
    maces=[f['mace_geometry']for f in native['families'].values()if f.get('mace_geometry')]
    if maces:
        if any(not np.allclose(list(m.values()),list(maces[0].values()),atol=1e-7)for m in maces[1:]):
            raise ValueError('Mace families do not share reviewed physical geometry')
        definitions.append(('mace','hazard','BoxCollider','mace',None))
    classes=[dict(name=n,kind=k,shape=s,motion_kind=m,phase=p,members=[])
             for n,k,s,m,p in definitions]
    if maces:
        entry=next(c for c in classes if c['name']=='mace');geometry=maces[0]
        entry['pivot_offset_ratio']=geometry['center_long']/geometry['long_side']
        entry['short_long_ratio']=geometry['short_side']/geometry['long_side']
    mapping=[]
    for c in native['classes']:
        if c['kind']=='player':index=0
        elif c['kind']in('rope','platform','floating_platform'):
            index={'rope':10,'platform':11,'floating_platform':12}[c['kind']]
        elif c.get('resource')=='EnemyFlyBamboo'and c.get('phase')in('aim','locked','attack'):
            index=next(i for i,entry in enumerate(classes)if entry['name']=='bamboo_'+c['phase'])
        elif c.get('resource')=='EnemyArrow'and native['families']['EnemyArrow'].get('arrow_family')and c['shape']=='BoxCollider':
            index=next(i for i,entry in enumerate(classes)if entry['name']=='arrow')
        elif native['families'].get(c.get('resource'),{}).get('mace_geometry')and c['shape']=='BoxCollider':
            index=next(i for i,entry in enumerate(classes)if entry['name']=='mace')
        elif c['shape']=='cue':index=9
        elif interactions and c.get('resource')in rules['resources']:
            rule=rules['resources'][c['resource']]
            if c['shape']!=rule['shape']:
                raise ValueError(f'Unreviewed interaction collider shape: {c["name"]}')
            index=next(i for i,entry in enumerate(classes)if entry['name']==rule['class'])
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
    result=dict(version=2,task='obb',geometry='gameplay_plane',taxonomy='physics',classes=classes,
                native_targets=native,class_mapping=mapping,families=native['families'],type_bindings=native['type_bindings'],
                provenance='Shared native collider/motion classes; original resources/configs remain in the profile')
    if interactions:
        result.update(interaction_rules=rules,interaction_rules_sha256=hashlib.sha256(INTERACTIONS.read_bytes()).hexdigest(),
                      target_policy_confidence=.8)
    return result


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


def visible_quad(quad):
    clipped=clipped_quad(quad)if quad is not None else None
    if clipped is not None:
        center=clipped.mean(0)
        if center[1]>275 and(center[0]<135 or center[0]>515):return None
    return clipped


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


def bamboo_marker_quad(obj):
    names={'Sprite','Outline (1)','Outline (2)','Outline (3)','Outline (4)',
           'Triangle (1)','Triangle (2)','Triangle (3)',
           'aim_laser','Outline1','Outline2','Outline3'}
    boxes=[r['box']for r in obj.get('renderers',[])if r.get('name')in names]
    if not boxes:return None
    a=np.asarray(boxes,float)
    return axis_quad([*a[:,:2].min(0),*a[:,2:].max(0)])


def targets(raw,profile):
    if profile.get('taxonomy')=='physics':
        native,counts=targets(raw,profile['native_targets'])
        mapped=[(profile['class_mapping'][cls],quad)for cls,quad in native]
        if profile.get('separate_bamboo_laser'):
            from arena_bamboo_geometry import retag_laser_targets
            mapped=retag_laser_targets(raw,mapped,profile)
        return mapped,counts
    row=normalize_arrays(raw)
    if row.get('label_schema',0)<4:
        raise ValueError('Full support supervision requires native label schema 4')
    keys={(c.get('resource'),c['shape'],c.get('phase','normal')):i for i,c in enumerate(profile['classes'])}
    support_ids={c['kind']:i for i,c in enumerate(profile['classes'])if c['shape']=='segment'}
    result=[];counts=Counter()
    def add(cls,quad):
        clipped=visible_quad(quad)
        if clipped is not None:
            result.append((cls,clipped.tolist()));counts['targets']+=1
            meta=profile['classes'][cls]
            if meta['kind']=='hazard':
                counts['resource:'+meta['resource']]+=1
                if len(meta.get('type_ids',[]))==1:
                    counts['type:'+str(meta['type_ids'][0])]+=1
    for collider in row['role']['colliders']or[]:add(0,collider_quad(collider))
    for obj in row.get('objects')or[]:
        if obj.get('dead')or not obj.get('renderers'):continue
        for collider in obj.get('colliders')or[]:
            if collider.get('owner_id')!=obj['id']:raise ValueError('Native collider ownership mismatch')
        resource=object_resource(obj,profile)
        if resource is None:
            counts['unbound_family']+=1
            for collider in obj.get('colliders')or[]:
                if is_damage_collider(obj,collider,profile.get('source_damage_modules',()))and visible_quad(collider_quad(collider))is not None:
                    counts['unbound_visible_targets']+=1
                    identity=obj.get('family_type_id',obj.get('source_type_id'))
                    counts['unbound_visible_type:'+str(identity)]+=1
            continue
        physical=[]
        for collider in obj.get('colliders')or[]:
            if collider.get('owner_id')!=obj['id']:raise ValueError('Native collider ownership mismatch')
            if is_damage_collider(obj,collider,profile.get('source_damage_modules',())):
                physical.append(collider)
                if is_attack_module_collider(obj,collider,profile.get('source_damage_modules',())):
                    counts['damage_module_colliders']+=1
                    if visible_quad(collider_quad(collider))is not None:counts['damage_module_visible_targets']+=1
            else:counts['auxiliary_colliders']+=1
        phase='normal'
        if profile['families'][resource].get('bamboo_phases')and physical:
            state=obj.get('controller',{}).get('_enemyState')
            if state is None:
                marker=bamboo_marker_quad(obj)
                if (any(visible_quad(collider_quad(c))is not None for c in physical)
                        or marker is not None and visible_quad(marker)is not None):
                    raise MissingBambooPhase('Visible FlyBamboo lacks native _enemyState')
                continue
            state=state.split(':')[0]
            phases={'none':'aim','aim':'aim','aimLock':'locked','readyAttack':'locked',
                    'flyToNinja':'attack','insertEdge':'attack'}
            if state not in phases:raise ValueError(f'Unreviewed native FlyBamboo phase: {state}')
            phase=phases[state]
            if phase!='attack':
                # The targeting reticle is near the middle of the image, far
                # from the thin AimLine collider at the right edge. Supervise
                # the visible reticle's phase at its own bounds, while retaining
                # that enabled original collider as ordinary physical geometry.
                marker=bamboo_marker_quad(obj)
                if marker is not None:add(keys[resource,'cue',phase],marker)
                phase='normal'
        if profile['families'][resource]['straight_bat']and physical:
            state=obj.get('controller',{}).get('_currState')
            if state is None:raise ValueError('Native straight-bat phase is required')
            phase={'ready':'ready','rushToNinja':'rush'}.get(state.split(':')[0],'normal')
        if physical:
            for collider in physical:
                module_phase=profile['families'][resource].get('damage_module_phases',{}).get(collider['type'])
                collider_phase=(module_phase if module_phase and is_attack_module_collider(
                    obj,collider,profile.get('source_damage_modules',())) else phase)
                key=(resource,collider['type'],collider_phase)
                if key not in keys:
                    counts['unconfigured_shape']+=1
                    if visible_quad(collider_quad(collider))is not None:counts['unconfigured_visible_targets']+=1
                    continue
                add(keys[key],collider_quad(collider))
        else:
            boxes=[r['box']for r in obj['renderers']]
            if boxes:
                a=np.asarray(boxes,float)
                add(keys[resource,'cue','normal'],axis_quad([*a[:,:2].min(0),*a[:,2:].max(0)]))
    for support in row.get('supports')or[]:
        if support.get('hidden')or support['kind']not in('rope','platform'):continue
        kind='floating_platform'if support.get('floating')else support['kind']
        add(support_ids[kind],segment_quad(support['start'],support['finish'],profile.get('support_band_px',4)))
    return result,counts


def supervision_quad(cls,quad):
    """A learnable arrow band preserves its physical centerline, not width."""
    band=cls.get('supervision_band_px')
    if band is None:return quad
    q=np.asarray(quad,float);center=q.mean(0);edges=(q[1]-q[0],q[2]-q[1]);edge=max(edges,key=lambda e:float(e@e))
    length=float(np.linalg.norm(edge));unit=edge/max(length,1e-6);normal=np.array([-unit[1],unit[0]])*band/2
    a=center-unit*length/2;b=center+unit*length/2
    expanded=np.array([a-normal,b-normal,b+normal,a+normal],np.float32)
    clipped=visible_quad(expanded)
    return clipped if clipped is not None else quad


def build(output,train,validation,entities_path,prefabs_path,plan_path,physics=False,support_band_px=4,interactions=False,bamboo_phases=False,arrow_family=False,arrow_band_px=None,mace_family=False):
    if interactions and not physics:raise ValueError('Interaction taxonomy requires the standard physics profile')
    if mace_family and not physics:raise ValueError('Mace motion family requires the standard physics profile')
    if arrow_band_px is not None and(not physics or not arrow_family or not 4<=arrow_band_px<=16):
        raise ValueError('Arrow supervision band requires its original physics family and 4..16 pixels')
    if not 4<=support_band_px<=32:raise ValueError('Support supervision band must be 4..32 px')
    if {p.resolve()for p in train}&{p.resolve()for p in validation}:
        raise ValueError('Whole native episodes must be disjoint')
    def episode_keys(folders):
        return {(s['seed'],s['level'],s['map'])for s in
                (json.loads((folder/'setup.json').read_text())for folder in folders)}
    if episode_keys(train)&episode_keys(validation):
        raise ValueError('A native map seed cannot cross dataset splits')
    plan=json.loads(plan_path.read_text())
    if plan.get('mode')!=6:raise ValueError('Only Gale resource pools may enter this dataset')
    profile=schema(json.loads(entities_path.read_text()),json.loads(prefabs_path.read_text()),plan['reachable_enemy_types'],bamboo_phases,arrow_family,mace_family)
    profile['support_band_px']=support_band_px
    if physics:profile=physics_profile(profile,interactions=interactions)
    if arrow_band_px is not None:
        arrow=next(c for c in profile['classes']if c['name']=='arrow')
        arrow.update(supervision_band_px=float(arrow_band_px),inference_short_side_world=.07000000029802322)
        profile['arrow_supervision_scope']='Training band only; targets() and physical scoring keep original native quads; inference restores the exported 0.07-world collider width'
    output.mkdir(parents=True,exist_ok=False)
    episodes=[*train,*validation];name_counts=Counter(folder.name for folder in episodes)
    episode_keys={str(folder):(folder.name if name_counts[folder.name]==1 else
                 hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:12]+'-'+folder.name)for folder in episodes}
    runtime_names=defaultdict(set);runtime_types=defaultdict(set)
    manifest=dict(task='standard Ultralytics YOLO26 OBB',profile='profile.json',splits={},sources={},
                  image_episode_keys=episode_keys,
                  source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in(entities_path,prefabs_path,plan_path,Path(__file__))})
    if interactions:manifest['source_hashes'][str(INTERACTIONS)]=hashlib.sha256(INTERACTIONS.read_bytes()).hexdigest()
    for split,folders in [('train',train),('val',validation)]:
        (output/'images'/split).mkdir(parents=True);(output/'labels'/split).mkdir(parents=True)
        counts=Counter();per_class=Counter()
        for folder in folders:
            labels_file=folder/'labels.jsonl'
            manifest['sources'][str(folder)]=dict(split=split,sha256=hashlib.sha256(labels_file.read_bytes()).hexdigest())
            for line in labels_file.open():
                row=normalize_arrays(json.loads(line))
                try:labels,stats=targets(row,profile)
                except MissingBambooPhase:
                    # Omit the entire old image, not just its unlabeled bamboo:
                    # retaining it would teach a visible warning as background.
                    counts['excluded_missing_bamboo_phase_frames']+=1;continue
                counts.update(stats);counts['frames']+=1
                if stats['unbound_visible_targets']or stats['unconfigured_visible_targets']:
                    raise ValueError(f'Visible native collider has no ontology target: {folder}/{row["image"]}: {dict(stats)}')
                if split=='train':
                    for obj in row.get('objects')or[]:
                        resource=object_resource(obj,profile)
                        if resource:
                            runtime_names[resource].add(obj.get('resource_family',obj['name']).split('(Clone)',1)[0])
                            runtime_types[resource].add(obj['type'])
                name=episode_keys[str(folder)]+'-'+row['image']
                (output/'images'/split/name).symlink_to((folder/row['image']).resolve())
                text=[]
                for cls,quad in labels:
                    coordinates=np.asarray(supervision_quad(profile['classes'][cls],quad))/[640,360];per_class[str(cls)]+=1
                    text.append(str(cls)+' '+' '.join(f'{v:.7f}'for v in coordinates.ravel())+'\n')
                (output/'labels'/split/Path(name).with_suffix('.txt')).write_text(''.join(text))
        manifest['splits'][split]=dict(counts=counts,class_targets=per_class)
        if split=='train':
            # Resampling decisions use actual positive training labels only,
            # never validation/test sightings or source pool references.
            for key,prefix in [('native_training_targets_by_resource','resource:'),
                               ('native_training_targets_by_type','type:')]:
                manifest[key]={k[len(prefix):]:v for k,v in counts.items()if k.startswith(prefix)}
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
    p.add_argument('--support-band',type=float,default=4,help='Training band only; inference recovers the original zero-thickness centerline')
    a=p.parse_args();result=build(a.output,a.train,a.validation,a.entities,a.prefabs,a.plan,a.physics,a.support_band)
    print(json.dumps(result['splits']),flush=True)
