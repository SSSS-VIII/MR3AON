#!/usr/bin/env python3
"""Fine-tune an existing Ultralytics YOLO detector; no custom network/trainer."""
import argparse
import json
import hashlib
from pathlib import Path


def validate_transfer(weights,data):
    """Fine-tuning shared support heads must preserve their reviewed labels."""
    old_path=Path(weights).parent.parent/'profile.json';new_path=Path(data).parent/'profile.json'
    if not old_path.is_file()or not new_path.is_file():return None
    old=json.loads(old_path.read_text());new=json.loads(new_path.read_text())
    if old.get('task')!='obb'or new.get('task')!='obb':return None
    support={'rope','platform','floating_platform'}
    shared=({c['kind']for c in old['classes']}&{c['kind']for c in new['classes']})&support
    before=old.get('native_targets',old).get('support_band_px',4)
    after=new.get('native_targets',new).get('support_band_px',4)
    if shared and before!=after:
        raise ValueError(f'Existing support supervision changed from {before} to {after} px; inherit the checkpoint profile before continuing its support heads')
    return dict(shared_supports=sorted(shared),support_band_px=before,
                profiles={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in(old_path,new_path)})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True)
    p.add_argument('--weights',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--transfer',type=Path,help='Load compatible fine-tuned weights over the standard base checkpoint')
    p.add_argument('--epochs',type=int,default=30);p.add_argument('--batch',type=int,default=8)
    p.add_argument('--freeze',type=int,default=10,help='Standard Trainer freeze count; 0 fine-tunes the full existing model')
    p.add_argument('--imgsz',type=int,default=640);a=p.parse_args()
    # Use the standard model and Trainer; larger native datasets may adapt the
    # full existing backbone while small-data runs retain the frozen default.
    if a.output.exists():
        p.error('Use a new output directory')
    if a.freeze<0:p.error('Freeze count must be nonnegative')
    if not a.weights.is_file():
        raise FileNotFoundError(a.weights)
    if a.transfer and not a.transfer.is_file():raise FileNotFoundError(a.transfer)
    transfer_profile=validate_transfer(a.transfer or a.weights,a.data)
    from arena_yolo import offline_sdk
    sdk=offline_sdk();model=sdk.YOLO(str(a.weights))
    if a.transfer:
        model.load(str(a.transfer))
    model.train(data=str(a.data.resolve()),epochs=a.epochs,batch=a.batch,imgsz=a.imgsz,device=0,
        workers=2,cache=False,amp=True,freeze=a.freeze,seed=17,deterministic=True,plots=False,
        project=str(a.output.resolve().parent),name=a.output.name,exist_ok=False,
        optimizer='AdamW',lr0=.001,cos_lr=True,patience=10,close_mosaic=5,mosaic=.25,
        mixup=0,fliplr=0,flipud=0,hsv_h=.015,hsv_s=.2,hsv_v=.25,translate=.05,scale=.2)
    profile=a.data.parent/'profile.json'
    if profile.is_file():
        metadata=json.loads(profile.read_text())
        if list(model.names.values())!=[c['name']for c in metadata['classes']]:
            raise ValueError('Trained checkpoint and native resource profile differ')
        (a.output/'profile.json').write_bytes(profile.read_bytes())
    provenance={str(path):hashlib.sha256(path.read_bytes()).hexdigest()
                for path in(a.weights,a.data,*([a.transfer]if a.transfer else[]))}
    (a.output/'source-checkpoints.json').write_text(json.dumps(provenance,indent=2)+'\n')
    (a.output/'profile-transfer.json').write_text(json.dumps(transfer_profile,indent=2)+'\n')
    print(json.dumps(dict(output=str(a.output),best=str(a.output/'weights/best.pt'))),flush=True)


if __name__=='__main__':
    main()
