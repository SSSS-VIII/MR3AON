#!/usr/bin/env python3
"""Extend the original resource catalog with natively observed spawned enemies."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from arena_entity_catalog import Resources


def observe(folders):
    observed={};sources={}
    for folder in folders:
        path=folder/'labels.jsonl';sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        for line in path.open():
            for obj in json.loads(line).get('objects')or[]:
                identity=obj.get('family_type_id',obj.get('source_type_id',0))
                if identity<0:continue
                if identity==0:
                    if obj.get('dead')or not obj.get('renderers')or not any(c.get('tag')=='Enemy'for c in obj.get('colliders')or[]):continue
                    identity='zero:'+obj.get('resource_family',obj['name']).split('(Clone)',1)[0]
                entry=observed.setdefault(identity,dict(names=set(),scripts=set(),shapes=set(),object_frames=0))
                entry['names'].add(obj.get('resource_family',obj['name']).split('(Clone)',1)[0])
                entry['scripts'].add(obj['type']);entry['shapes'].update(c['type']for c in obj.get('colliders')or[])
                entry['object_frames']+=1
    return observed,sources


def extend(entities,prefabs,observed,configs,resources):
    entities=deepcopy(entities);prefabs=deepcopy(prefabs);index={e['type_id']:e for e in entities if e['kind']=='enemies'}
    extra=[]
    for identity,evidence in sorted(observed.items(),key=lambda pair:str(pair[0])):
        if isinstance(identity,str)and identity.startswith('zero:'):
            name=identity[5:]
            existing=next((e for e in entities if e.get('resource_name')==name),None)
            if existing:
                existing['zero_source_runtime_evidence']=evidence
                continue
            assets=[a for a in resources.containers if a.endswith('/'+name.lower()+'.prefab')]
            if len(assets)!=1:raise ValueError(f'Original zero-source prefab must be unique: {name}: {assets}')
            asset=assets[0];keys=[];scripts=set()
            for bundle,root_id in sorted({(source['bundle'],pointer['m_PathID'])for source,pointer in resources.containers[asset]}):
                key=bundle+'::'+asset+'#'+str(root_id)
                if key not in prefabs:prefabs[key]=resources.prefab(asset,bundle,root_id)
                keys.append(key);scripts.update(s['class_name']for s in prefabs[key]['scripts'])
            if not set(evidence['scripts'])<=scripts:raise ValueError(f'Native and original zero-source scripts differ: {name}')
            entities.append(dict(kind='runtime_enemies',type_id=None,source_type_id=0,resource_name=name,config=None,
                prefabs=keys,runtime_generated=True,native_spawn_verified=True,runtime_verified=False,runtime_evidence=evidence))
            continue
        old=index.get(identity)
        if old and old.get('gale_usage',{}).get('placements',0)>0:continue
        if old:
            old['runtime_generated']=True;old['runtime_evidence']=evidence;extra.append(identity);continue
        config=configs.get(identity);name=config.get('resourceName')if config else None
        row=dict(kind='enemies',type_id=identity,resource_name=name,config=config,prefabs=[],
                 gale_usage=dict(placements=0,stages=[]),runtime_generated=True,runtime_evidence=evidence,
                 status='missing_current_config'if config is None else'resources_indexed',
                 native_spawn_verified=True,runtime_verified=False)
        if name:
            suffix='/'+name.lower()+'.prefab'
            assets=[a for a in resources.containers if a.endswith(suffix)]
            if len(assets)!=1:raise ValueError(f'Original spawned prefab must be unique: {identity}/{name}: {assets}')
            asset=assets[0]
            for bundle,root_id in sorted({(source['bundle'],pointer['m_PathID'])for source,pointer in resources.containers[asset]}):
                key=bundle+'::'+asset+'#'+str(root_id)
                if key not in prefabs:prefabs[key]=resources.prefab(asset,bundle,root_id)
                row['prefabs'].append(key)
        entities.append(row);extra.append(identity)
    return entities,prefabs,extra


def ontology_plan(plan,extra):
    if plan.get('mode')!=6:raise ValueError('Only Gale ontology may be extended')
    result=deepcopy(plan)
    result['directly_placed_enemy_types']=list(plan['reachable_enemy_types'])
    result['runtime_generated_types']=sorted(extra)
    result['reachable_enemy_types']=sorted(set(plan['reachable_enemy_types'])|set(extra))
    result['scope']='Dataset ontology: original pool entries unchanged, plus natively observed generated types; not a new collection plan'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in('entities','prefabs','configs','plan','output'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--episodes',type=Path,nargs='+',required=True);p.add_argument('--resources',type=Path,nargs='+',required=True)
    a=p.parse_args();observed,sources=observe(a.episodes)
    configs={}
    for entry in json.loads(a.configs.read_text()):
        for value in entry['values']:
            if not isinstance(value,dict)or'ID'not in value:continue
            identity=value['ID']
            if identity in configs and configs[identity]!=value:raise ValueError(f'Conflicting original configuration: {identity}')
            configs[identity]=value
    # Explicit input folders determine the provenance; training callers supply
    # training episodes only. No validation images are borrowed into training.
    serial={identity:{k:sorted(v)if isinstance(v,set)else v for k,v in row.items()}for identity,row in observed.items()}
    resources=Resources(a.resources)
    entities,prefabs,extra=extend(json.loads(a.entities.read_text()),json.loads(a.prefabs.read_text()),serial,configs,resources)
    a.output.mkdir(parents=True,exist_ok=False)
    for name,value in [('entities',entities),('prefabs',prefabs)]:
        (a.output/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
    (a.output/'dataset-ontology.json').write_text(json.dumps(ontology_plan(json.loads(a.plan.read_text()),extra),indent=2)+'\n')
    sources.update({str(path):hashlib.sha256(path.read_bytes()).hexdigest()for path in(a.entities,a.prefabs,a.configs,a.plan)})
    report=dict(runtime_generated_types=extra,source_hashes=sources,resource_exports=resources.exports,
                zero_source_resources=[e['resource_name']for e in entities if e['kind']=='runtime_enemies'],
                scope='Native spawn evidence plus exact original CFG/Prefab binding; not direct board placements or detector acceptance')
    (a.output/'runtime-generated.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
