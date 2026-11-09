#!/usr/bin/env python3
"""Plan finite training-only revisits from actual native generated layouts."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from arena_yolo_obb_data import targets


def select(profile,counts,episodes,minimum=1,limit=8):
    wanted={r for r in profile['families']if counts.get(r,0)<minimum};remaining=set(wanted);candidates={}
    for folder,setup,layout in episodes:
        if layout['stage_id']!=setup['board']:raise ValueError('Recorded native stage differs from its setup')
        blocks=layout['blocks']
        for index,block in enumerate(blocks):
            resources={profile['type_bindings'].get(str(e['source_type_id']))for e in block.get('enemies')or[]}
            resources.discard(None);resources&=wanted
            if not resources:continue
            landing=index
            while landing>0 and blocks[landing]['finish_x']-blocks[landing]['start_x']<4:landing-=1
            if landing==(setup.get('sample_block')or 0):continue
            spec={key:setup[key]for key in('level','map','start','board')};spec['sample_block']=landing
            key=(setup['seed'],*spec.values())
            entry=candidates.setdefault(key,dict(spec=spec,replay_training_seed=setup['seed'],resources=set(),enemy_types=set(),
                unresolved_types=[],source_episode=str(folder),native_target_blocks=set()))
            entry['resources']|=resources;entry['enemy_types'].update(e['source_type_id']for e in block.get('enemies')or[]
                if profile['type_bindings'].get(str(e['source_type_id']))in resources)
            entry['native_target_blocks'].add(index)
    selected=[]
    while remaining and candidates and len(selected)<limit:
        key=min(candidates,key=lambda k:(-len(candidates[k]['resources']&remaining),
                candidates[k]['spec']['start'],candidates[k]['spec']['level'],candidates[k]['spec']['sample_block'],k))
        entry=candidates.pop(key);new=entry['resources']&remaining
        if not new:break
        selected.append({k:sorted(v)if isinstance(v,set)else v for k,v in entry.items()})
        remaining-=new
    return dict(mode=6,minimum_capture_schema=4,minimum_native_frame_targets=minimum,
                reachable_enemy_types=sorted(map(int,profile['type_bindings'])),known_visible_training_targets=dict(counts),
                selected=selected,not_planned=sorted(remaining),target_resources=sorted(wanted),
                scope='Revisit recorded training seeds at actual generated block indices; no validation/test seeds or forced spawns')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',type=Path,required=True);p.add_argument('--collections',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--minimum',type=int,default=1);p.add_argument('--limit',type=int,default=8)
    a=p.parse_args()
    if a.minimum<1 or a.limit<1:p.error('Positive limits are required')
    profile=json.loads(a.profile.read_text());profile=profile.get('native_targets',profile)
    episodes=[];counts=Counter();sources={str(a.profile):hashlib.sha256(a.profile.read_bytes()).hexdigest()}
    seen=set()
    for manifest in a.collections:
        sources[str(manifest)]=hashlib.sha256(manifest.read_bytes()).hexdigest()
        for job in json.loads(manifest.read_text())['jobs'].values():
            if job['split']!='train'or job['status']!='complete':continue
            folder=Path(job['folder'])
            if folder.resolve()in seen:continue
            seen.add(folder.resolve())
            for filename in('setup.json','layout.json','labels.jsonl'):
                sources[str(folder/filename)]=hashlib.sha256((folder/filename).read_bytes()).hexdigest()
            episodes.append((folder,json.loads((folder/'setup.json').read_text()),json.loads((folder/'layout.json').read_text())))
            for line in(folder/'labels.jsonl').open():
                labels,_=targets(json.loads(line),profile)
                for cls,_ in labels:
                    resource=profile['classes'][cls].get('resource')
                    if resource:counts[resource]+=1
    result=select(profile,counts,episodes,a.minimum,a.limit);result['source_hashes']=sources
    with a.output.open('x')as f:f.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(windows=len(result['selected']),target_resources=result['target_resources'],not_planned=result['not_planned'])),flush=True)
