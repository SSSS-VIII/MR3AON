#!/usr/bin/env python3
"""Save a paused 640px frame and original collider labels, then show the pause menu."""
import argparse
import json
from pathlib import Path
import time
from arena_local import LocalClient,ROOT
from arena_capture import FastCapture
from runtime import InstanceSession
from PIL import Image


def snapshot(output):
    output.mkdir(parents=True,exist_ok=False)
    session=InstanceSession('arena')
    client=LocalClient(session)
    source=(ROOT/'arena/Local/vision_labels.lua').read_text()
    try:
        client.execute('MR3A.pause();MR3A.menu_suppressed=true;MR3A.hide_menu();'
                       'assert(load('+json.dumps(source)+'))();return true')
        with FastCapture(session,width=640,height=360)as capture:
            frame=capture.capture()
            labels=client.execute('return MR3A.vision_labels()',lease_held=True)
            Image.frombytes('RGBA',(640,360),frame.rgba).convert('RGB').save(output/'frame.png')
            (output/'labels.json').write_text(json.dumps(labels,indent=2)+'\n')
        return labels
    finally:
        client.execute('MR3A.pause();MR3A.menu_suppressed=false;MR3A.enable_menu();return true')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'debug/arena-client/vision-labels'/str(time.time_ns()))
    args=parser.parse_args()
    labels=snapshot(args.output)
    print(json.dumps(dict(output=str(args.output),objects=len(labels['objects']),tick=labels['tick'])))


if __name__=='__main__':
    main()
