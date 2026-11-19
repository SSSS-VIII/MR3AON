#!/usr/bin/env python3
"""Exercise each native-proven fixed program through the real visual runner.

This grades individual board entries, not uninterrupted arena no-hit runs.
The actor still gets pixels/own inputs only. Native samples are post-run grades.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

from arena_fixed_validate import review

ROOT=Path(__file__).resolve().parents[1]


def actor_sources():
    seen=set()
    todo=[ROOT/'tools'/name for name in ('arena_visual_runner.py','arena_fixed_policy.py','arena_fixed_match.py')]
    while todo:
        path=todo.pop()
        if path in seen or not path.is_file():continue
        seen.add(path)
        try:tree=ast.parse(path.read_bytes())
        except SyntaxError:continue  # The actor itself will retain this failure.
        for node in ast.walk(tree):
            modules=([a.name for a in node.names]if isinstance(node,ast.Import)else
                     [node.module]if isinstance(node,ast.ImportFrom)and node.level==0 and node.module else [])
            for module in modules:
                name=module.split('.')[0]
                if name.startswith('arena_'):todo.append(ROOT/'tools'/(name+'.py'))
    return sorted(seen)


def fingerprint(bundle,seed):
    files=[bundle/'manifest.json',bundle/'programs.json',*actor_sources(),
           *sorted((ROOT/'arena').glob('vision-*.json'))]
    files.extend(p for p in(ROOT/'tools/arena_fixed_validate.py',Path(__file__))if p.is_file())
    hashes=[(str(p),hashlib.sha256(p.read_bytes()).hexdigest())for p in files]
    return hashlib.sha256(json.dumps([hashes,seed]).encode()).hexdigest()


def pending(bundle,cases,ledger,seeds,*,repeats=1):
    if type(repeats)is not int or repeats<1:raise ValueError('Use a positive repeat count')
    programs=json.loads((bundle/'programs.json').read_text())['programs']
    work=[]
    for repeat in range(repeats):
        for seed in seeds:
            version=fingerprint(bundle,seed)
            for key,program in programs.items():
                if not program.get('native_passed')or key not in cases:
                    continue
                job=f'{key}:{seed}:{version}:repeat{repeat}'
                if ledger.get(job,{}).get('status')in ('graded','failed'):
                    continue
                work.append(dict(job=job,key=key,seed=seed,version=version,program=program,repeat=repeat))
    return sorted(work,key=lambda j:(not j['program'].get('timing_robust',False),
        cases[j['key']]['level']not in (5,6),j['repeat'],seeds.index(j['seed']),j['key']))


def stability(bundle,cases,ledger,seeds,*,repeats):
    """All required runs must pass under the same exact bank and actor version."""
    required=pending(bundle,cases,{},seeds,repeats=repeats);result={}
    for job in required:
        item=result.setdefault(job['key'],dict(required=0,passed=0,failed=0,pending=0,stable_no_damage=False))
        item['required']+=1;entry=ledger.get(job['job'],{})
        if entry.get('status')=='graded'and entry.get('grade',{}).get('live_runner_verified')is True:
            item['passed']+=1
        elif entry.get('status')in('graded','failed'):item['failed']+=1
        else:item['pending']+=1
    for item in result.values():item['stable_no_damage']=item['passed']==item['required']and item['failed']==0
    return dict(scope='Finite repeated individual-board visual trials; not an all-seed guarantee',
                seeds=list(seeds),repeats=repeats,cases=result)


def frozen_config(bundle,output):
    bundle=Path(bundle).resolve();path=output/'configs'/bundle.name/'fixed-routes.json'
    payload=dict(schema=1,bundle=str(bundle),atlas=str(bundle/'atlas'),programs=str(bundle/'programs.json'))
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if json.loads(path.read_text())!=payload:raise RuntimeError('Frozen runtime configuration changed')
    else:path.write_text(json.dumps(payload,indent=2))
    return path


def baseline_signature():
    paths=[ROOT/'tools/arena_fixed_oracle_audit.py',ROOT/'tools/arena_checkpoint_lab/oracle_route.lua',
           ROOT/'arena/Local/environment.lua',ROOT/'arena/Local/native_selection.lua',ROOT/'arena/Local/vision_eval.lua']
    return hashlib.sha256(json.dumps([(str(p),hashlib.sha256(p.read_bytes()).hexdigest())for p in paths]).encode()).hexdigest()


def baseline_pending(bundle,cases,ledger):
    programs=json.loads((bundle/'programs.json').read_text())['programs']
    signature=baseline_signature()
    work=[]
    for key,program in sorted(programs.items()):
        if not program.get('native_passed')or key not in cases:continue
        source=Path(program['source']);raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=program['source_sha256']:
            raise RuntimeError('The native program source changed after publication')
        seed=json.loads(raw)['start']['state']['seed']
        for mode,fps in (('source_intervals',60),('continuous_ticks',60),('continuous_ticks',0)):
            job=f'{key}:{program["source_sha256"]}:{seed}:{mode}:{fps}:{signature}'
            if ledger.get(job,{}).get('status')in ('graded','failed'):continue
            work.append(dict(job=job,key=key,seed=seed,mode=mode,capture_fps=fps,
                             route_sha256=program['source_sha256'],auditor_signature=signature))
    return work


def save(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    temporary.replace(path)


def execute(command,log):
    with log.open('xb')as stream:
        child=subprocess.Popen(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        try:
            return child.wait(timeout=480)
        except (KeyboardInterrupt,subprocess.TimeoutExpired):
            child.send_signal(signal.SIGINT)
            try:child.wait(timeout=60)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--repeats',type=int,default=3,help='Independent fresh entries for each seed')
    args=parser.parse_args()
    if args.repeats<1:parser.error('--repeats must be positive')
    # File lock protects the scheduler; each actual actor obtains arena's
    # existing InstanceSession lease itself, without private ADB/Waydroid logic.
    import fcntl
    args.output.mkdir(parents=True,exist_ok=True)
    lock=(args.output/'batch.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    ledger_path=args.output/'ledger.json'
    ledger=json.loads(ledger_path.read_text())if ledger_path.exists()else{}
    baseline_path=args.output/'baseline-ledger.json'
    baselines=json.loads(baseline_path.read_text())if baseline_path.exists()else{}
    cases={c['key']:c for c in json.loads((args.queue/'inventory.json').read_text())['contexts']}
    seeds=[55200,55201,55202]
    while True:
        bundle=(args.runtime/'current').resolve()
        if not(bundle/'manifest.json').is_file()or not(bundle/'programs.json').is_file():
            save(args.output/'watch-state.json',dict(phase='waiting_for_bundle',bundle=str(bundle),updated_at=time.time()))
            if not args.watch:return
            time.sleep(30);continue
        checks=baseline_pending(bundle,cases,baselines)
        if checks:
            from arena_fixed_oracle_audit import audit
            check=checks[0]
            folder=args.output/'baselines'/check['key']/str(time.time_ns())
            entry=dict(check,status='running',output=str(folder),started_at=time.time())
            baselines[check['job']]=entry;save(baseline_path,baselines)
            save(args.output/'watch-state.json',dict(phase='baseline',job=check['job'],
                                                   output=str(folder),updated_at=time.time()))
            print('无视觉跑法复验',check['key'],check['mode'],check['capture_fps'],flush=True)
            try:
                result=audit(args.queue,check['key'],folder,check['mode'],check['capture_fps'],check['seed'])
                if result['route_sha256']!=check['route_sha256']or not result['sources_unchanged']:
                    raise RuntimeError('Oracle evidence changed during the independent execution')
                entry.update(status='graded',passed=result['passed'],no_damage=result['no_damage'],
                             input_schedule_exact=result['input_schedule_exact'])
            except KeyboardInterrupt:
                entry.update(status='interrupted');save(baseline_path,baselines);raise
            except Exception as error:entry.update(status='failed',error=repr(error))
            finally:
                entry['finished_at']=time.time();save(baseline_path,baselines)
            continue
        work=pending(bundle,cases,ledger,seeds,repeats=args.repeats)
        save(args.output/'stability.json',stability(bundle,cases,ledger,seeds,repeats=args.repeats))
        if not work:
            save(args.output/'watch-state.json',dict(phase='waiting_for_new_evidence',bundle=str(bundle),updated_at=time.time()))
            if not args.watch:return
            time.sleep(30)
            continue
        job=work[0];case=cases[job['key']]
        folder=args.output/'runs'/job['key']/str(time.time_ns())
        folder.parent.mkdir(parents=True,exist_ok=True)
        entry=dict(key=job['key'],seed=job['seed'],repeat=job['repeat'],bundle=str(bundle),version=job['version'],
                   status='running',output=str(folder),started_at=time.time())
        ledger[job['job']]=entry;save(ledger_path,ledger)
        print('视觉单板验收',job['key'],'seed',job['seed'],'repeat',job['repeat'],flush=True)
        config=frozen_config(bundle,args.output)
        command=[sys.executable,str(ROOT/'tools/arena_visual_runner.py'),'--level',str(case['level']),
            '--map',str(case['map']),'--start',str(case['slot']),'--pin',f'{case["slot"]}:{case["stage"]}',
            '--boards','1','--seconds','120','--seed',str(job['seed']),'--output',str(folder),
            '--fixed-routes',str(config)]
        save(args.output/'watch-state.json',dict(phase='visual_trial',job=job['job'],output=str(folder),updated_at=time.time()))
        try:
            code=execute(command,folder.with_suffix('.log'))
            entry['runner_exit_code']=code
            if not(folder/'report.json').exists():
                raise RuntimeError(f'Visual runner exited {code} without a complete report')
            setup=json.loads((folder/'setup.json').read_text())
            expected=str(bundle/'programs.json')
            expected_sha=hashlib.sha256((bundle/'programs.json').read_bytes()).hexdigest()
            if setup.get('fixed_route_assets',{}).get(expected)!=expected_sha:
                raise RuntimeError('Runtime bank changed or was rejected; do not grade the expected program')
            if setup.get('fixed_route_config')!=str(config.resolve()):
                raise RuntimeError('The actor did not load the requested frozen runtime configuration')
            result=review(folder,case,job['program'])
            save(folder/'fixed-validation.json',result)
            record=args.queue/'validation'/job['key'];record.mkdir(parents=True,exist_ok=True)
            save(record/(result['source_sha256']+'.json'),result)
            entry.update(status='graded',grade=result)
            print('视觉验收结果',job['key'],result['status'],'无伤验收',result['live_runner_verified'],flush=True)
        except KeyboardInterrupt:
            entry.update(status='interrupted');save(ledger_path,ledger);raise
        except Exception as error:
            entry.update(status='failed',error=repr(error))
            print('保留视觉失败',job['key'],repr(error),flush=True)
        finally:
            entry['finished_at']=time.time();save(ledger_path,ledger)


if __name__=='__main__':main()
