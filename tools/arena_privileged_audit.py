#!/usr/bin/env python3
"""Check frozen internal forecasts against later original-client observations."""
import argparse
from collections import defaultdict
import json
import inspect
import hashlib
from pathlib import Path
import sys
import numpy as np


def summary(values):
    if not values:
        return dict(count=0)
    a = np.asarray(values)
    return dict(count=len(a), p50=float(np.quantile(a,.5)), p95=float(np.quantile(a,.95)), max=float(a.max()))


def audit(folder, model_source=None):
    # Import the actual frozen code of this run, even if working files have
    # subsequently changed. Start this CLI in its own Python interpreter.
    if 'arena_privileged_model' in sys.modules:
        raise RuntimeError('Audit in a clean interpreter so frozen code is used')
    source=model_source or folder/'sources'
    sys.path.insert(0,str(source))
    from arena_privileged_model import PlayerModel, hazard_forecasts, rows
    data = [json.loads(line) for line in (folder/'decisions.jsonl').read_text().splitlines()]
    accumulated = defaultdict(lambda: defaultdict(list))
    mismatch = defaultdict(lambda:dict(checked=0,mismatched=0))
    rejected = defaultdict(int)
    stamps = np.asarray([r['observation']['state']['time'] for r in data])
    worst = []
    for i,row in enumerate(data):
        before = row['observation']
        for horizon in (.05,.1,.25,.5):
            j = int(np.searchsorted(stamps, stamps[i]+horizon))
            if j >= len(data):
                rejected['tail_without_observation'] += 1; continue
            if j>i+1 and abs(stamps[j-1]-stamps[i]-horizon) < abs(stamps[j]-stamps[i]-horizon):
                j -= 1
            if j<=i or abs(stamps[j]-stamps[i]-horizon) > .0251:
                rejected['clock_sample_missing'] += 1; continue
            if any(r['delivered'] != 'none' for r in data[i+1:j]):
                rejected['another_input_before_target'] += 1; continue
            after = data[j]['observation']; elapsed = stamps[j]-stamps[i]
            times = np.linspace(0.,elapsed,max(2,round(elapsed*120)+1))
            model = PlayerModel(before)
            body,motors,valid = model.trajectory(times, () if row['delivered']=='none' else ((0.,row['delivered']),))
            key = str(horizon)
            if not valid:
                rejected['invalid_action_forecast'] += 1; continue
            actual_body = rows(after['role']['colliders'])[0]
            error = [abs(float(body[-1,k]-actual_body['center'][axis]))for k,axis in enumerate(('x','y'))]
            accumulated[key]['player_x_m'].append(error[0]); accumulated[key]['player_y_m'].append(error[1])
            worst.append(dict(row=i, horizon=horizon, player_y_error_m=error[1],
                              original=before['state']['physics'], actual=after['state']['physics'], action=row['delivered']))
            hazards,missing = (hazard_forecasts(before,times,model,motors) if
                               len(inspect.signature(hazard_forecasts).parameters)>3 else hazard_forecasts(before,times,model))
            actual = {c['id']:(c,e) for e in rows(after['enemies']) for c in rows(e['colliders'])}
            originals = {e['id']:e for e in rows(before['enemies'])}
            for h in hazards:
                if h.id not in actual:
                    rejected['enemy_left_original_scene'] += 1; continue
                c,owner=actual[h.id]
                old_owner=originals[h.enemy]
                if (owner['type']!=old_owner['type'] or owner['fields'].get('m_index')!=old_owner['fields'].get('m_index')
                        or owner.get('info_identity')!=old_owner.get('info_identity')):
                    rejected['pooled_object_reused_for_another_spawn'] += 1; continue
                actual_active=c['active'] and c['enabled']
                identity=key+':'+h.kind
                mismatch[identity]['checked'] += 1
                mismatch[identity]['mismatched'] += int(bool(h.active[-1]) != actual_active)
                if not h.active[-1] or not actual_active:
                    continue
                for k,axis in enumerate(('x','y')):
                    accumulated[key][h.kind+'_'+axis+'_m'].append(abs(float(h.centers[-1,k]-c['center'][axis])))
    return dict(scope='Forecast versus later original state; no intervening unmodeled input; not route certification',
                candidate_model=model_source is not None, model_source=str(source),
                model_sha256=hashlib.sha256((source/'arena_privileged_model.py').read_bytes()).hexdigest(),
                observations=len(data), horizons={k:{n:summary(v) for n,v in metrics.items()} for k,metrics in accumulated.items()},
                activation=mismatch, excluded=dict(rejected),
                worst_player=sorted(worst,key=lambda r:r['player_y_error_m'],reverse=True)[:12])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model-source',type=Path,help='Explicit offline candidate comparison; default uses frozen run code')
    args=p.parse_args()
    if args.output.exists():
        p.error('Use a new audit output')
    result=audit(args.run,args.model_source)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['horizons'],ensure_ascii=False))


if __name__=='__main__':
    main()
