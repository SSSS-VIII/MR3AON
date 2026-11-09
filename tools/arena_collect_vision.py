#!/usr/bin/env python3
"""Collect paused, paired original frames/collider labels in the arena instance.

Engine time, rather than wall time spent paused for RPC/disk IO, indexes tracks.
Labels are training/evaluation only and are never passed to the deployed actor.
"""
from __future__ import annotations
import os
if __name__ == '__main__':
    for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
        os.environ[key]='1'
import argparse
import hashlib
import json
from pathlib import Path
import time
import cv2
from arena_local import LocalClient, ROOT
from arena_capture import FastCapture
from arena_visual_runner import prepare
from runtime import InstanceSession


def collect(output, *, seed=42, board=11012, seconds=18, ticks=4):
    output.mkdir(parents=True,exist_ok=False)
    cv2.setNumThreads(1)
    session=InstanceSession('arena'); client=LocalClient(session)
    source=(ROOT/'arena/Local/vision_labels.lua').read_text()
    count=0
    try:
        initial=prepare(client,seed,1,1,{'1':board})
        client.execute('assert(load('+json.dumps(source)+'))();return true')
        (output/'setup.json').write_text(json.dumps(dict(seed=seed,board=board,ticks=ticks,
            seconds=seconds,initial=initial,label_sha256=hashlib.sha256(source.encode()).hexdigest()),indent=2)+'\n')
        with FastCapture(session,width=640,height=360) as capture, (output/'labels.jsonl').open('w') as log:
            start=None
            while True:
                labels=client.execute('return MR3A.vision_labels()',lease_held=True)
                if start is None:
                    start=labels['engineTime']
                frame=capture.capture()
                filename=f'{count:06d}.png'
                if not cv2.imwrite(str(output/filename),cv2.cvtColor(frame.array(),cv2.COLOR_RGBA2BGR)):
                    raise OSError(filename)
                labels.update(image=filename,index=count,t=labels['engineTime']-start)
                log.write(json.dumps(labels)+'\n');log.flush();count+=1
                if count%100==0:
                    print(json.dumps(dict(frames=count,time=labels['t'],health=labels['health'])),flush=True)
                if labels['t']>=seconds or labels['health']<=0:
                    break
                client.execute(f'return MR3A.advance({ticks},"none")',lease_held=True)
                deadline=time.monotonic()+10
                while True:
                    job=client.execute('return {done=MR3A.job.done,error=MR3A.job.error}',lease_held=True)
                    if job['done']:
                        if job.get('error'):
                            raise RuntimeError(job['error'])
                        break
                    if time.monotonic()>deadline:
                        raise TimeoutError('Native collection step')
                    time.sleep(.01)
        return dict(output=str(output),frames=count,seconds=labels['t'],health=labels['health'])
    finally:
        client.execute('MR3A.pause();MR3A.menu_suppressed=false;MR3A.enable_menu();return true')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--board',type=int,default=11012)
    parser.add_argument('--seconds',type=float,default=18)
    parser.add_argument('--ticks',type=int,default=4)
    args=parser.parse_args()
    if not 0<args.seconds<=90 or not 1<=args.ticks<=10:
        parser.error('Collection limits out of range')
    print(json.dumps(collect(args.output,seed=args.seed,board=args.board,seconds=args.seconds,ticks=args.ticks)))


if __name__=='__main__':
    main()
