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
    hashes=[(str(p),hashlib.sha256(p.read_bytes()).hexdigest())for p in files]
    return hashlib.sha256(json.dumps([hashes,seed]).encode()).hexdigest()


def pending(bundle,cases,ledger,seeds):
    programs=json.loads((bundle/'programs.json').read_text())['programs']
    work=[]
    for seed in seeds:
        version=fingerprint(bundle,seed)
        for key,program in programs.items():
            if not program.get('native_passed')or key not in cases:
                continue
            job=f'{key}:{seed}:{version}'
            if ledger.get(job,{}).get('status')in ('graded','failed'):
                continue
            work.append(dict(job=job,key=key,seed=seed,version=version,program=program))
    return sorted(work,key=lambda j:(cases[j['key']]['level']not in (5,6),seeds.index(j['seed']),j['key']))


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
    args=parser.parse_args()
    # File lock protects the scheduler; each actual actor obtains arena's
    # existing InstanceSession lease itself, without private ADB/Waydroid logic.
    import fcntl
    args.output.mkdir(parents=True,exist_ok=True)
    lock=(args.output/'batch.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    ledger_path=args.output/'ledger.json'
    ledger=json.loads(ledger_path.read_text())if ledger_path.exists()else{}
    cases={c['key']:c for c in json.loads((args.queue/'inventory.json').read_text())['contexts']}
    while True:
        bundle=(args.runtime/'current').resolve()
        work=pending(bundle,cases,ledger,[55200,55201,55202])
        if not work:
            if not args.watch:return
            time.sleep(30)
            continue
        job=work[0];case=cases[job['key']]
        folder=args.output/'runs'/job['key']/str(time.time_ns())
        folder.parent.mkdir(parents=True,exist_ok=True)
        entry=dict(key=job['key'],seed=job['seed'],bundle=str(bundle),version=job['version'],
                   status='running',output=str(folder),started_at=time.time())
        ledger[job['job']]=entry;save(ledger_path,ledger)
        print('视觉单板验收',job['key'],'seed',job['seed'],flush=True)
        command=[sys.executable,str(ROOT/'tools/arena_visual_runner.py'),'--level',str(case['level']),
            '--map',str(case['map']),'--start',str(case['slot']),'--pin',f'{case["slot"]}:{case["stage"]}',
            '--boards','1','--seconds','120','--seed',str(job['seed']),'--output',str(folder)]
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
