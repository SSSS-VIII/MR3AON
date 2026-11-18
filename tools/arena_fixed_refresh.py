#!/usr/bin/env python3
"""Compile new native exit evidence into an atomic research runtime bundle."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]


def signature(queue):
    data=json.loads((queue/'coverage.json').read_text())
    return [(key,item['route'],item.get('references'))for key,item in data['cases'].items()
            if item.get('native_passed')and item.get('route')]


def refresh(queue,runtime):
    from arena_fixed_publish import publish
    before=signature(queue)
    package=runtime/'bundles'/str(time.time_ns())
    package.mkdir(parents=True)
    environment=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    command=[sys.executable,str(ROOT/'tools/arena_fixed_build.py'),'--queue',str(queue),
             '--legacy-root',str(ROOT/'debug/arena-client/yolo/finetune/native'),
             '--legacy-root',str(ROOT/'debug/arena-client/yolo/finetune/rope-recovery-v37'),
             '--cache',str(runtime/'feature-cache'),
             '--output',str(package/'atlas')]
    with (package/'build.log').open('w')as log:
        subprocess.run(command,cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
    if signature(queue)!=before:
        raise RuntimeError('Native evidence changed during compilation; keep candidate and retry next update')
    # Publish only routes present when compilation started. A case finishing
    # meanwhile is picked up by the next iteration, not mixed into this bank.
    coverage=json.loads((queue/'coverage.json').read_text())
    eligible={key for key,_,_ in before}
    coverage['cases']={key:item for key,item in coverage['cases'].items()if key in eligible}
    publish(coverage,json.loads((queue/'inventory.json').read_text()),package/'programs.json')
    manifest=dict(schema=1,signature=before,visual_execution_verified=False,
        files={str(path.relative_to(package)):hashlib.sha256(path.read_bytes()).hexdigest()
               for path in (package/'atlas/index.json',package/'atlas/features.npz',package/'programs.json')})
    (package/'manifest.json').write_text(json.dumps(manifest,indent=2))
    temporary=runtime/'current.next'
    if temporary.is_symlink():temporary.unlink()
    temporary.symlink_to(package.relative_to(runtime),target_is_directory=True)
    os.replace(temporary,runtime/'current')
    print('Published native-proven research bank:',len(before),package,flush=True)
    return before


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    args.runtime.mkdir(parents=True,exist_ok=True)
    lock=(args.runtime/'refresh.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    previous=None
    while True:
        current=signature(args.queue)
        if current and current!=previous:
            try:previous=refresh(args.queue,args.runtime)
            except Exception as error:
                print('Compilation not published:',repr(error),flush=True)
                previous=current
                if not args.watch:raise
        if not args.watch:return
        time.sleep(30)


if __name__=='__main__':main()
