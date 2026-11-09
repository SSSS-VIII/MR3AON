#!/usr/bin/env python3
"""Select actual Gale board pools for missing native visual training resources."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def build_plan(catalog,entities,placements,known,minimum=100):
    if catalog.get('mode')!=6:
        raise ValueError('Only original Gale mode pools are supported')
    if minimum<1:
        raise ValueError('Minimum target count must be positive')
    enemies={e['type_id']:e for e in entities if e['kind']=='enemies'}
    stages=defaultdict(set)
    groups=defaultdict(lambda:defaultdict(set))
    for row in placements:
        if row['kind']=='enemies':
            stages[row['stage']].add(row['type_id'])
            groups[row['stage']][row.get('group',0)].add(row['type_id'])
    candidates=[];reachable=set()
    for level in catalog['levels']:
        for entry in level['maps']:
            map_id=entry['id'];world=catalog['maps'][str(map_id)]
            pools=[slot['pool']for slot in world['slots']]
            if world.get('loop'):pools.append(world['loop'])
            for position,pool in enumerate(pools,1):
                for variant in pool:
                    stage=variant['id'];ids=stages[stage];reachable.update(ids)
                    for group in sorted(groups[stage]):
                        window=groups[stage][group]|groups[stage].get(group+1,set())
                        resources={enemies[i]['resource_name']for i in window
                                   if i in enemies and enemies[i].get('config')is not None
                                   and enemies[i].get('resource_name')}
                        unresolved={i for i in window if i not in enemies or enemies[i].get('config')is None}
                        if resources or unresolved:
                            spec=dict(level=level['id'],map=map_id,start=position,board=stage)
                            if group>1:spec['sample_block']=group-1
                            candidates.append(dict(spec=spec,source_groups=[group,group+1],unresolved_types=sorted(unresolved),
                                                   enemy_types=sorted(window),resources=sorted(resources)))
    missing=sorted(i for i in reachable if i not in enemies or enemies[i].get('config')is None)
    unbound=sorted(i for i in reachable if i in enemies and enemies[i].get('config')is not None
                   and not enemies[i].get('resource_name'))
    all_resources=set().union(*(set(c['resources'])for c in candidates))if candidates else set()
    covered={r for r,n in known.items()if n>=minimum};uncovered=all_resources-covered
    unknown=set(missing)
    target=sorted(uncovered);selected=[]
    while uncovered or unknown:
        candidate=min(candidates,key=lambda c:(-len(set(c['resources'])&uncovered)-len(set(c['unresolved_types'])&unknown),
                      c['spec'].get('sample_block',0),c['spec']['level'],c['spec']['map'],c['spec']['start'],c['spec']['board']))
        new=set(candidate['resources'])&uncovered
        probes=set(candidate['unresolved_types'])&unknown
        if not new and not probes:break
        selected.append(dict(candidate,new_resources=sorted(new),new_unresolved_types=sorted(probes)))
        uncovered-=new
        unknown-=probes
    return dict(mode=6,minimum_native_frame_targets=minimum,known_native_counts=known,
                reachable_enemy_types=sorted(reachable),missing_current_config=missing,
                unbound_resource_types=unbound,target_resources=target,selected=selected,
                not_planned=sorted(uncovered),not_planned_unresolved_types=sorted(unknown),
                scope='Native pool selection only; placement/reference coverage is not observed visual coverage')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog',type=Path,required=True);p.add_argument('--entities',type=Path,required=True)
    p.add_argument('--placements',type=Path,required=True);p.add_argument('--known-native',type=Path,required=True)
    p.add_argument('--minimum',type=int,default=100);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    known=json.loads(a.known_native.read_text())['native_training_targets_by_resource']
    result=build_plan(json.loads(a.catalog.read_text()),json.loads(a.entities.read_text()),
                      [json.loads(s)for s in a.placements.read_text().splitlines()],known,a.minimum)
    result['source_hashes']={str(path):hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in(a.catalog,a.entities,a.placements,a.known_native)}
    with a.output.open('x')as out:out.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(selected_boards=len(result['selected']),resources=len(result['target_resources']),
                          missing_config=result['missing_current_config'],unbound=result['unbound_resource_types'])))


if __name__=='__main__':main()
