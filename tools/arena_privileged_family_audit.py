#!/usr/bin/env python3
"""Compare passive native observations with internal mechanism predictions.

Inputs are paused native observations collected without keys between samples.
Reports retain unsupported phases and both all-pair and no-injury errors; a
small prediction error never becomes board or timing acceptance.
"""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from arena_privileged_model import PlayerModel,hazard_forecasts,rows


def summarize(values):
    return dict(count=len(values),p50=float(np.percentile(values,50)),
                p95=float(np.percentile(values,95)),maximum=float(max(values))) if values else dict(count=0)


def audit(observations, *, offsets=(1,2,5)):
    stats=defaultdict(lambda:defaultdict(list));missing=Counter();pooled=0
    for index,before in enumerate(observations):
        for offset in offsets:
            if index+offset>=len(observations):
                continue
            after=observations[index+offset]
            dt=after['state']['time']-before['state']['time']
            if not .01<dt<.6 or after['state']['seed']!=before['state']['seed']:
                continue
            times=np.linspace(0.,dt,round(dt*120)+1)
            hazards,unmapped=hazard_forecasts(before,times,PlayerModel(before))
            missing.update((e['type'],e['reason']) for e in unmapped)
            originals={e['id']:e for e in rows(before['enemies'])}
            actual={c['id']:(e,c) for e in rows(after['enemies']) for c in rows(e['colliders'])}
            for hazard in hazards:
                if hazard.id not in actual:
                    continue
                enemy,collider=actual[hazard.id];old=originals.get(enemy['id'])
                if old is None or old['info_identity']!=enemy['info_identity']:
                    pooled+=1;continue
                enabled=bool(collider['active'] and collider['enabled'])
                result=stats[hazard.kind]
                result['activation_mismatch'].append(int(bool(hazard.active[-1])!=enabled))
                if not enabled:
                    continue
                position=np.array([collider['center'][a] for a in ('x','y')])
                extent=np.array([collider['extents'][a] for a in ('x','y')])
                error=float(np.linalg.norm(position-hazard.centers[-1]))
                result['position_error_all_m'].append(error)
                unchanged=after['state']['health']==before['state']['health']
                feedback=old['fields'].get('_bCollider',False) or enemy['fields'].get('_bCollider',False)
                if unchanged and not feedback:
                    result['position_error_without_injury_or_blade_feedback_m'].append(error)
                # A target-growth envelope intentionally overestimates a
                # partially extended blade. Report its containment separately.
                result['planning_padding_m'].append(hazard.padding)
                miss=np.maximum(0.,np.abs(position-hazard.centers[-1])+extent-hazard.extents[-1]-hazard.padding)
                result['aabb_containment_excess_m'].append(float(np.linalg.norm(miss)))
                result['extent_error_m'].append(float(np.linalg.norm(extent-hazard.extents[-1])))
    return dict(types={kind:{name:summarize(v) for name,v in values.items()} for kind,values in stats.items()},
        missing=[dict(type=kind,reason=reason,count=count) for (kind,reason),count in missing.items()],
        pooled_pairs_excluded=pooled)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs',type=Path,nargs='+')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Keep prior evidence; choose a new output file')
    result=dict(schema=1,scope='Passive native prediction comparison, not route acceptance',inputs={})
    for path in args.inputs:
        data=path.read_bytes()
        observations=[json.loads(line) for line in data.splitlines()]
        result['inputs'][str(path)]=dict(sha256=hashlib.sha256(data).hexdigest(),observations=len(observations),
                                       **audit(observations))
    sources=('arena_privileged_model.py','arena_privileged_families.py','arena_privileged_geometry.py',
             'arena_privileged_pinball.py','arena_privileged_family_audit.py')
    result['source_hashes']={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in sources}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(inputs=len(args.inputs),output=str(args.output))))


if __name__=='__main__':
    main()
