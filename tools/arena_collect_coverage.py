#!/usr/bin/env python3
"""Collect a finite, resumable Gale coverage plan using only the arena instance."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import time

from arena_native_json import normalize_arrays


def audit_rows(rows,minimum_schema=3):
    """Count observed native targets, separately from source pool references."""
    spawned=Counter();visible=Counter();families=Counter();shapes=Counter();poses=Counter()
    particle=Counter();support=Counter();frames=0;last=None;floating=0
    for raw in rows:
        row=normalize_arrays(raw)
        if row.get('label_schema',0)<max(3,minimum_schema):
            raise ValueError(f'Coverage collection requires native label schema {max(3,minimum_schema)}')
        frames+=1;last=row;poses[row['physics']]+=1
        for obj in row.get('objects')or[]:
            source=obj.get('source_type_id',0);family=obj.get('family_type_id',source)
            spawned[str(source)]+=1
            for c in obj.get('colliders')or[]:
                if c['owner_id']!=obj['id']:
                    raise ValueError('Collider belongs to another native enemy')
            if obj.get('dead')or not obj.get('renderers'):
                continue
            boxes=[c['box']for c in obj.get('colliders')or[]]
            if not boxes:
                continue
            x1=min(b[0]for b in boxes);y1=min(b[1]for b in boxes)
            x2=max(b[2]for b in boxes);y2=max(b[3]for b in boxes)
            if min(640,x2)-max(0,x1)<2 or min(360,y2)-max(0,y1)<2:
                continue
            visible[str(family)]+=1
            families[obj.get('resource_family',obj['name']).split('(Clone)',1)[0]]+=1
            if obj.get('particle_only'):particle[str(family)]+=1
            shapes.update(c['type']for c in obj.get('colliders')or[])
        support.update(s['kind']for s in row.get('supports')or[] if not s.get('hidden'))
        floating+=sum(bool(s.get('floating'))for s in row.get('supports')or[] if not s.get('hidden'))
    return dict(frames=frames,spawned_object_frame_counts_by_source_type=dict(spawned),
                visible_target_frame_counts_by_family_type=dict(visible),
                visible_target_frame_counts_by_resource_family=dict(families),
                particle_only_target_frame_counts_by_family_type=dict(particle),
                visible_collider_frame_counts_by_shape=dict(shapes),
                visible_support_frame_counts_by_kind=dict(support),visible_floating_support_frame_targets=floating,poses=dict(poses),
                final_health=last['health']if last else None,
                seconds=last.get('t')if last else None)


def jobs_for(plan,splits,base_seed):
    offsets={'train':0,'val':1,'test':2}
    if not splits or len(set(splits))!=len(splits)or any(s not in offsets for s in splits):
        raise ValueError('Expected distinct train/val/test splits')
    if plan.get('mode')!=6:
        raise ValueError('Only Gale collection is supported')
    return [dict(split=split,window=i,seed=base_seed+i*3+offsets[split],spec=entry['spec'],
                 expected_resources=entry['resources'],expected_types=entry['enemy_types'])
            for i,entry in enumerate(plan['selected'])for split in splits]


def summarize(state,plan):
    by_split={};deaths=[];short=[];failed=[];completed=0
    for key,job in state['jobs'].items():
        if job['status']!='complete':
            if job['status']=='failed':failed.append(key)
            continue
        completed+=1
        evidence=next(a for a in reversed(job['attempts'])if a['status']=='complete')
        coverage=evidence['coverage'];split=by_split.setdefault(job['split'],dict(frames=0,types=Counter(),resources=Counter()))
        split['frames']+=coverage['frames']
        split['types'].update(coverage['visible_target_frame_counts_by_family_type'])
        split['resources'].update(coverage['visible_target_frame_counts_by_resource_family'])
        if coverage['final_health']<=0:deaths.append(key)
        if coverage['seconds']<state['configuration']['seconds']*.8:short.append(key)
    observed=set().union(*(set(map(int,s['types']))for s in by_split.values()))if by_split else set()
    return dict(completed_jobs=completed,planned_jobs=len(plan['selected'])*len(state['configuration']['splits']),
                failed_jobs=failed,death_episodes=deaths,short_episodes=short,by_split=by_split,
                observed_family_type_count=len(observed),
                unobserved_native_types=sorted(set(plan['reachable_enemy_types'])-observed),
                scope='Observed viewport targets only; a complete episode may contain death or miss its requested types')


def run(plan_path,output,*,splits=('train','val','test'),base_seed=20000,seconds=10,ticks=3,limit=None):
    # Import live dependencies only for execution; auditing/tests need no GPU/CV.
    from arena_collect_vision import collect
    from arena_local import ROOT
    plan=json.loads(plan_path.read_text());jobs=jobs_for(plan,splits,base_seed)
    if limit is not None:jobs=jobs[:limit]
    output.mkdir(parents=True,exist_ok=True)
    identity=dict(plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                  splits=list(splits),base_seed=base_seed,seconds=seconds,ticks=ticks)
    manifest=output/'collection.json'
    if manifest.exists():
        state=json.loads(manifest.read_text())
        if state['configuration']!=identity:
            raise ValueError('Resume configuration differs from the existing collection')
    else:state=dict(configuration=identity,jobs={})

    def save():
        temp=manifest.with_suffix('.tmp');temp.write_text(json.dumps(state,indent=2)+'\n');temp.replace(manifest)
        summary=output/'summary.json';temp=summary.with_suffix('.tmp')
        temp.write_text(json.dumps(summarize(state,plan),indent=2)+'\n');temp.replace(summary)

    save()
    for job in jobs:
        key=f"{job['split']}-w{job['window']:02d}-s{job['seed']}"
        previous=state['jobs'].get(key,{})
        if previous.get('status')=='complete':continue
        record=dict(job,status='running',attempts=previous.get('attempts',[]));state['jobs'][key]=record;save()
        for _ in range(2):
            attempt=len(record['attempts'])+1;folder=output/f'{key}-a{attempt}'
            evidence=dict(folder=str(folder),status='running');record['attempts'].append(evidence);save()
            spec=job['spec'];begin=time.monotonic()
            print(json.dumps(dict(job=key,attempt=attempt,spec=spec)),flush=True)
            try:
                result=collect(folder,seed=job['seed'],seconds=seconds,ticks=ticks,explore=True,
                               board=spec['board'],start=spec['start'],level=spec['level'],
                               map_id=spec['map'],sample_block=spec.get('sample_block'))
                summary=audit_rows((json.loads(line)for line in(folder/'labels.jsonl').open()),
                                   minimum_schema=plan.get('minimum_capture_schema',3))
                (folder/'coverage.json').write_text(json.dumps(summary,indent=2)+'\n')
                evidence.update(status='complete',result=result,coverage=summary)
                record.update(status='complete',folder=str(folder));save()
                print(json.dumps(dict(job=key,frames=summary['frames'],health=summary['final_health'],
                                      observed=summary['visible_target_frame_counts_by_family_type'])),flush=True)
                break
            except Exception as error:
                evidence.update(status='failed',error=str(error),wall_seconds=time.monotonic()-begin)
                record['status']='failed';save()
                # Only the known native preparation fault permits app recovery.
                # Lease conflicts or annotation/transport faults must not restart
                # a client another controller may own, or hide bad training data.
                if 'RecycleAllMainAirGround'not in str(error)or attempt>=2:
                    print(json.dumps(dict(job=key,error=str(error))),flush=True);break
                recovery=output/f'{key}-recovery{attempt}.log'
                with recovery.open('w')as log:
                    recovered=subprocess.run([str(ROOT/'tools/run-arena'),'--restart','--paused','--no-focus',
                                              '--seed','48','--level','1'],cwd=ROOT,stdout=log,
                                             stderr=subprocess.STDOUT,timeout=300)
                evidence['recovery_log']=str(recovery);evidence['recovery_exit_code']=recovered.returncode;save()
                if recovered.returncode:break
        save()
    return state


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--splits',nargs='+',default=['train','val','test'])
    p.add_argument('--base-seed',type=int,default=20000);p.add_argument('--seconds',type=float,default=10)
    p.add_argument('--ticks',type=int,default=3);p.add_argument('--limit',type=int)
    a=p.parse_args()
    if not 0<a.seconds<=90 or not 1<=a.ticks<=10 or a.limit is not None and a.limit<1:
        p.error('Collection limits out of range')
    state=run(a.plan,a.output,splits=a.splits,base_seed=a.base_seed,seconds=a.seconds,ticks=a.ticks,limit=a.limit)
    failed=sum(j['status']!='complete'for j in state['jobs'].values())
    print(json.dumps(dict(jobs=len(state['jobs']),failed=failed)),flush=True)
    raise SystemExit(1 if failed else 0)
