#!/usr/bin/env python3
"""Re-measure Xiaohei primitives through original UI in the isolated client.

Outputs raw samples and a candidate prior file in the private debug directory.
It does not overwrite the reviewed policy priors in arena/ automatically.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from arena_local import LocalClient,ROOT
from runtime import InstanceSession
import numpy as np


def wait(client,expression,timeout=90):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=client.execute('return '+expression,timeout=20)
        if result and result.get('done'):
            if result.get('error'):
                raise RuntimeError(result['error'])
            return result
        time.sleep(.05)
    raise TimeoutError(expression)


def prepare(client):
    client.execute('return MR3A.native_select({level=1,map=1,start=1,pins={["1"]=1101}},42)')
    wait(client,'MR3A.travel')
    client.execute('MR3A.menu_suppressed=true;MR3A.hide_menu();return true')
    client.execute('return MR3A.advance(80,"none")')
    wait(client,'MR3A.job')


def distill(paths):
    result=dict(version=1,client='2.0.109 / dynamicPatch 1248',role=1,skin=1,
        hold_seconds=.08,clock='UnityEngine.Time.time',stand_width=.36,
        stand_height=.936,stand_offset_x=.052,profiles={})
    for name,path in paths.items():
        rows=json.loads(path.read_text())['samples']
        initial=rows[0]
        samples=[]
        for row in rows:
            if name.startswith('jump') and row['t']>.1 and row['physics'].startswith('runOnLine:'):
                break
            if name.startswith('rope') and row['t']>.34:
                break
            samples.append(row)
        points=[[round(row['t'],7),round(row['cx']-row['x'],7),
                 round(row['y']-initial['y'],7),round(row['cy']-row['y'],7),
                 round(row['w'],7),round(row['h'],7)]for row in samples]
        data=dict(initial_offset_y=round(initial['cy']-initial['y'],7),points=points,
                  source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        if name.startswith('jump'):
            falling=[row for row in samples if row['physics'].startswith('fall')]
            ts=np.array([row['t']for row in falling]);ys=np.array([row['y']for row in falling])
            a,b,c=np.polyfit(ts,ys,2)
            data.update(tail_velocity=round(float(2*a*ts[-1]+b),7),
                        tail_acceleration=round(float(2*a),7),apex=round(falling[0]['t'],7))
        else:
            endpoint=-.75 if name=='rope_down'else.75
            settled=next(row for row in samples if row['t']>.02 and abs(row['y']-endpoint)<.001 and row['h']>.9)
            data['duration']=round(settled['t'],7)
        result['profiles'][name]=data
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'debug/arena-client/motion-calibration'/str(time.time_ns()))
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    client=LocalClient(InstanceSession('arena'))
    source=(ROOT/'arena/Local/vision_probe.lua').read_text()
    paths={}
    try:
        prepare(client)
        client.execute(source)
        for name,action in [('rope_down','down'),('rope_up','jump'),('jump1','jump')]:
            client.execute(f'return MR3A.probe_action("{action}",40,4)')
            paths[name]=args.output/f'{name}-native.json'
            paths[name].write_text(json.dumps(wait(client,'MR3A.visionProbe'),indent=2))
        prepare(client)
        client.execute('return MR3A.advance(8,"jump")')
        wait(client,'MR3A.job')
        client.execute('return MR3A.probe_action("jump",45,4)')
        paths['jump2']=args.output/'jump2-native.json'
        paths['jump2'].write_text(json.dumps(wait(client,'MR3A.visionProbe'),indent=2))
        (args.output/'motion-priors.json').write_text(json.dumps(distill(paths),indent=2)+'\n')
        print(args.output)
    finally:
        client.execute('MR3A.pause();MR3A.menu_suppressed=false;MR3A.enable_menu();return true')


if __name__=='__main__':
    main()
