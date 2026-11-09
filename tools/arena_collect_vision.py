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
import uuid
import random
import cv2
from arena_local import LocalClient, ROOT,FOLDER
from arena_capture import FastCapture
from arena_visual_runner import prepare
from runtime import InstanceSession
from arena_native_json import normalize_arrays


def collect(output, *, seed=42, board=11012, seconds=18, ticks=4,explore=False,pins=None,start=1,level=1,map_id=1):
    output.mkdir(parents=True,exist_ok=False)
    cv2.setNumThreads(1)
    session=InstanceSession('arena'); client=LocalClient(session)
    source=(ROOT/'arena/Local/vision_labels.lua').read_text()
    paired=(ROOT/'arena/Local/paired_collection.lua').read_text()
    rng=random.Random(seed);last_action=-10
    count=0
    try:
        selected={str(start):board}|(pins or {})
        initial=prepare(client,seed,level,map_id,selected,start=start)
        client.execute('assert(load('+json.dumps(source)+'))();assert(load('+json.dumps(paired)+'))();return true')
        (output/'setup.json').write_text(json.dumps(dict(seed=seed,board=board,ticks=ticks,
            seconds=seconds,initial=initial,explore=explore,pins=selected,start=start,level=level,map=map_id,
            collection_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            preparation_sha256=hashlib.sha256((ROOT/"tools/arena_visual_runner.py").read_bytes()).hexdigest(),
            label_sha256=hashlib.sha256(source.encode()).hexdigest(),
            paired_sha256=hashlib.sha256(paired.encode()).hexdigest()),indent=2)+'\n')
        with FastCapture(session,width=640,height=360) as capture, (output/'labels.jsonl').open('w') as log:
            start=None;labels=client.execute('return MR3A.vision_labels()',lease_held=True)
            while True:
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
                action='none'
                if explore and labels['t']-last_action>.65 and rng.random()<.12:
                    action=rng.choice(['jump','down']);last_action=labels['t']
                identity=uuid.uuid4().hex
                client.execute(f'return MR3A.paired_step({ticks},"{action}","{identity}")',lease_held=True)
                deadline=time.monotonic()+10
                while True:
                    result=session.adb('shell','cat',FOLDER+'/paired-collection.json')
                    try:
                        job=json.loads(result.stdout)
                    except ValueError:
                        job={}
                    if job.get('done')and job.get('identity')==identity:
                        if job.get('error'):
                            raise RuntimeError(job['error'])
                        labels=normalize_arrays(job['labels']);labels['previous_action']=action
                        break
                    if time.monotonic()>deadline:
                        raise TimeoutError('Native collection step')
                    time.sleep(.01)
        return dict(output=str(output),frames=count,seconds=labels['t'],health=labels['health'])
    finally:
        # An interrupted host read must let the already-running original advance
        # complete; pausing it halfway would leave E.busy until its native timeout.
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if not client.execute('return MR3A.busy'):
                break
            time.sleep(.05)
        client.execute('MR3A.pause();MR3A.menu_suppressed=false;MR3A.enable_menu();return true')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--board',type=int,default=11012)
    parser.add_argument('--seconds',type=float,default=18)
    parser.add_argument('--start',type=int,default=1,help='Native board position at which paired collection begins')
    parser.add_argument('--level',type=int,default=1,help='Native absolute Gale level')
    parser.add_argument('--map',type=int,default=1,help='Map ID in the native level pool')
    parser.add_argument('--ticks',type=int,default=4)
    parser.add_argument('--explore',action='store_true',help='Sample original jump/flip actions for pose coverage')
    parser.add_argument('--pin',action='append',default=[],help='Native board choice position:variant')
    args=parser.parse_args()
    if not 0<args.seconds<=90 or not 1<=args.ticks<=10 or min(args.start,args.level,args.map)<1:
        parser.error('Collection limits out of range')
    pins={key:int(value)for key,value in(item.split(':',1)for item in args.pin)}
    print(json.dumps(collect(args.output,seed=args.seed,board=args.board,seconds=args.seconds,ticks=args.ticks,
                             explore=args.explore,pins=pins,start=args.start,level=args.level,map_id=args.map)))


if __name__=='__main__':
    main()
