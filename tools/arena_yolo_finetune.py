#!/usr/bin/env python3
"""Fine-tune an existing Ultralytics YOLO detector; no custom network/trainer."""
import argparse
import json
from pathlib import Path
from arena_yolo import offline_sdk


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True)
    p.add_argument('--weights',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=30);p.add_argument('--batch',type=int,default=8)
    p.add_argument('--imgsz',type=int,default=640);a=p.parse_args()
    # The standard model/trainer remain intact; only the first backbone layers
    # are frozen during this small-data adaptation.
    if a.output.exists():
        p.error('Use a new output directory')
    if not a.weights.is_file():
        raise FileNotFoundError(a.weights)
    sdk=offline_sdk();model=sdk.YOLO(str(a.weights))
    model.train(data=str(a.data.resolve()),epochs=a.epochs,batch=a.batch,imgsz=a.imgsz,device=0,
        workers=2,cache=False,amp=True,freeze=10,seed=17,deterministic=True,plots=False,
        project=str(a.output.resolve().parent),name=a.output.name,exist_ok=False,
        optimizer='AdamW',lr0=.001,cos_lr=True,patience=10,close_mosaic=5,mosaic=.25,
        mixup=0,fliplr=0,flipud=0,hsv_h=.015,hsv_s=.2,hsv_v=.25,translate=.05,scale=.2)
    print(json.dumps(dict(output=str(a.output),best=str(a.output/'weights/best.pt'))),flush=True)


if __name__=='__main__':
    main()
