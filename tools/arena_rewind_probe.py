"""Isolated evidence for native rollback research; does not implement restore.

The default command only prints the bounded plan. --execute compares original
reset/input replays and reports discrepancies; it never calls them snapshots.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def tick_schedule(steps, step_ms=50, native_tick_ms=20):
    """Quantize elapsed targets, keeping the original 20ms physics unchanged."""
    if type(steps)is not int or not 1<=steps<=200:
        raise ValueError('Steps must be1..200')
    if type(native_tick_ms)is not int or native_tick_ms<=0:
        raise ValueError('Native tick duration must be positive')
    if type(step_ms)is not int or not native_tick_ms<=step_ms<=200:
        raise ValueError('Requested step must be20..200ms')
    target=Fraction(step_ms,native_tick_ms)
    previous=0;result=[]
    for index in range(1,steps+1):
        current=(index*target.numerator)//target.denominator
        result.append(current-previous);previous=current
    return result


def canonical(snapshot):
    """Compare recorded gameplay evidence, explicitly excluding Unity clocks.

    This is an audit projection, not a complete state hash. Private managed
    references, engine/physics internals, coroutines and presentation are absent.
    """
    value=deepcopy(snapshot)
    value.pop('engine',None)
    for key in ('frame','time'):
        value.get('state',{}).pop(key,None)
    value['objects']=sorted(value.get('objects',[]),key=lambda x:json.dumps(x,sort_keys=True))
    return value


def differences(left,right,path='',limit=30):
    result=[]
    def visit(a,b,p):
        if len(result)>=limit:return
        if isinstance(a,dict)and isinstance(b,dict):
            for key in sorted(set(a)|set(b)):
                if key not in a or key not in b:result.append(dict(path=p+'/'+key,left=a.get(key),right=b.get(key)))
                else:visit(a[key],b[key],p+'/'+key)
                if len(result)>=limit:return
        elif isinstance(a,list)and isinstance(b,list):
            if len(a)!=len(b):result.append(dict(path=p+'/length',left=len(a),right=len(b)))
            for index,(x,y)in enumerate(zip(a,b)):visit(x,y,p+'/'+str(index))
        elif a!=b:result.append(dict(path=p,left=a,right=b))
    visit(left,right,path)
    return result


def audit(output, *, steps=20, step_ms=50, seed=55200):
    from arena_bootstrap import wait_job
    from arena_local import LocalClient
    from arena_visual_runner import prepare
    from runtime import InstanceSession
    schedule=tick_schedule(steps,step_ms)
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    session=InstanceSession('arena')
    class Held(LocalClient):
        def execute(self,*args,**kwargs):
            kwargs['lease_held']=True
            return super().execute(*args,**kwargs)
    client=Held(session)
    source=ROOT/'arena/Local/rewind_probe.lua'
    dependencies=[source,Path(__file__).resolve(),ROOT/'arena/Local/environment.lua',
                  ROOT/'tools/arena_visual_runner.py',ROOT/'arena/Local/native_selection.lua']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()for p in dependencies}
    plan=dict(schema=1,seed=seed,level=5,map=43,start=1,pins={'1':53012},
              requested_step_ms=step_ms,native_tick_ms=20,ticks=schedule,
              scope='Original reset/replay diagnostic, not full rollback, search or no-hit acceptance.',
              source_hashes=hashes)
    (output/'plan.json').write_text(json.dumps(plan,indent=2))
    runs=[];restored=False
    with session.control():
        initial=client.execute('return MR3A.state()')
        if initial.get('timeScale')!=0:raise RuntimeError('Pause arena before the probe')
        client.execute(source.read_text())
        try:
            for repetition in range(2):
                prepare(client,seed,5,43,{'1':53012},timeout=120)
                client.execute('MR3A.visionEvalEnabled=false;return true')
                rows=[]
                for index,ticks in enumerate([0,*schedule]):
                    action='jump' if index in (4,9) else 'down' if index in (6,12) else 'none'
                    job=None
                    if ticks:
                        client.execute(f'return MR3A.advance({ticks},{json.dumps(action)})')
                        job=wait_job(client,'MR3A.job',timeout=20)
                    snapshot=client.execute('return MR3A.rewindProbe.capture()')
                    actual=(job['after']['episodeFrame']-job['before']['episodeFrame'])if job else 0
                    rows.append(dict(index=index,action=action,requested_ticks=ticks,actual_ticks=actual,snapshot=snapshot))
                    if snapshot['state']['health']<=0:break
                runs.append(rows)
                (output/f'run-{repetition}.json').write_text(json.dumps(rows,indent=2))
        finally:
            if client.execute('return MR3A.busy'):
                wait_job(client,'MR3A.job',timeout=20)
            if not client.execute('return MR3A.busy'):
                client.execute('return MR3A.rewindProbe.close()')
                prepare(client,42,1,1,{'1':1101},timeout=120)
                state=client.execute('MR3A.pause();MR3A.visionEvalEnabled=false;MR3A.menu_suppressed=false;MR3A.enable_menu();MR3A.enable_keyboard();return MR3A.state()')
                (output/'restored.json').write_text(json.dumps(state,indent=2))
                restored=True
            (output/'cleanup.json').write_text(json.dumps(dict(restored=restored)))
    results=[]
    for a,b in zip(*runs):
        delta=differences(canonical(a['snapshot']),canonical(b['snapshot']))
        results.append(dict(index=a['index'],same_observed_fields=not delta,differences=delta))
    bad=[p for p,h in hashes.items()if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h]
    report=dict(schema=1,full_state_restore_implemented=False,
                comparable_steps=len(results),matching_steps=sum(r['same_observed_fields']for r in results),
                exact_tick_counts=all(row['actual_ticks']==row['requested_ticks']for run in runs for row in run),
                source_mismatches=bad,restored=restored,rows=results,
                scope='Only the exported fields are compared. Equality would not prove full state restoration; omitted state is not silently accepted.')
    (output/'report.json').write_text(json.dumps(report,indent=2))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'debug/arena-client/rewind-research-v1/native-replay-audit')
    parser.add_argument('--steps',type=int,default=20)
    args=parser.parse_args()
    if not args.execute:
        print(json.dumps(dict(instance='arena',requested_step_ms=50,native_tick_ms=20,
                              ticks=tick_schedule(args.steps),full_restore=False,execute=False)))
        return
    result=audit(args.output,steps=args.steps)
    print(json.dumps({k:v for k,v in result.items()if k!='rows'}))


if __name__=='__main__':main()
