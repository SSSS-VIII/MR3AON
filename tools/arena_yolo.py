#!/usr/bin/env python3
"""Evaluate existing YOLO/YOLOE weights on original arena frames, without training.

YOLOE visual prompts are reference examples, never target-frame ground truth.
All images/checkpoints/results stay under the private debug directory.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import numpy as np
import cv2


def offline_sdk():
    os.environ['YOLO_OFFLINE']='true'
    os.environ.setdefault('YOLO_CONFIG_DIR',str(Path(__file__).resolve().parents[1]/'debug/arena-client/yolo/config'))
    import ultralytics
    ultralytics.settings.update({'sync':False})
    return ultralytics


def make_reference(data,output):
    """Initial reference bank from one independent native-labeled episode."""
    output.mkdir(parents=True,exist_ok=False)
    types={'EnemySpider':'spider','EnemyStraightBat':'crow','EnemyPinball':'pinball'}
    chosen={}
    for line in (data/'labels.jsonl').open():
        row=json.loads(line)
        for obj in row['objects']or[]:
            name=types.get(obj['type'])
            if name in chosen or name is None or not obj['colliders']:
                continue
            a=np.asarray([c['box']for c in obj['colliders']])
            lo=a[:,:2].min(0);hi=a[:,2:].max(0);cx,cy=(lo+hi)/2
            if 300<cx<510 and 95<cy<(225 if name=='spider'else 275):
                chosen[name]=(row['image'],lo,hi,obj['type'])
        if len(chosen)==3:
            break
    if len(chosen)!=3:
        raise ValueError('Reference episode lacks the three initial enemy families')
    canvas=np.full((384,640,3),114,np.uint8);boxes=[];classes=[];records=[]
    for i,(name,(file,lo,hi,typename))in enumerate(chosen.items()):
        image=cv2.imread(str(data/file));cx,cy=(lo+hi)/2
        # Native collider boxes are only visual example locations, not predicted
        # detector boxes nor an assertion of runtime collision equivalence.
        radius=int(max(35,(hi-lo).max()*.75))
        x,y=int(cx)-radius,int(cy)-radius
        patch=image[y:y+2*radius,x:x+2*radius]
        patch=cv2.resize(patch,(160,160))
        ox=25+i*210;oy=100;canvas[oy:oy+160,ox:ox+160]=patch
        factor=160/(2*radius)
        boxes.append([ox+(lo[0]-x)*factor,oy+(lo[1]-y)*factor,
                      ox+(hi[0]-x)*factor,oy+(hi[1]-y)*factor]);classes.append(i)
        records.append(dict(name=name,source=str(data/file),native_type=typename,box=boxes[-1]))
    cv2.imwrite(str(output/'reference.png'),canvas)
    result=dict(schema=1,classes=[r['name']for r in records],examples=records,
                bboxes=boxes,cls=classes,image='reference.png',training=False,
                scope='Three families only; full resource catalog does not imply detector coverage')
    (output/'reference.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def asset_profile(weights,references,output,keys=None,device='0'):
    """Encode native prefab silhouettes with the existing YOLOE visual encoder."""
    if not weights.is_file():
        raise FileNotFoundError(weights)
    YOLOE=offline_sdk().YOLOE
    from ultralytics.data.augment import LoadVisualPrompt
    import torch
    output.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(2);cv2.setNumThreads(1)
    model=YOLOE(str(weights));model.to(device if device=='cpu'else 'cuda:'+device);model.model.eval()
    entries=json.loads((references/'references.json').read_text())
    chosen=[r for r in entries if not r.get('error')and r.get('image')
            and (keys is None or f'{r["kind"]}:{r["type_id"]}'in keys)]
    if keys is not None and len(chosen)!=len(set(keys)):
        raise ValueError('Requested native visual references are not all available')
    embeddings=[];names=[];sources=[]
    target=next(model.model.parameters()).device
    for ref in chosen:
        file=references/ref['image'];image=cv2.imread(str(file))
        corners=np.concatenate([image[:5,:5].reshape(-1,3),image[-5:,-5:].reshape(-1,3)])
        background=np.median(corners,axis=0)
        mask=(np.max(abs(image.astype(np.float32)-background),axis=2)>12).astype(np.float32)
        if ref.get('camera_focus')=='original_allRenderObj':
            x1,y1,x2,y2=ref['appearance_box'];region=np.zeros_like(mask)
            region[max(0,int(y1)):min(256,int(y2)+1),max(0,int(x1)):min(256,int(x2)+1)]=1
            mask*=region
        rgb=cv2.resize(image,(640,640))[:,:,::-1].transpose(2,0,1).copy()
        visual=cv2.resize(mask,(640,640),interpolation=cv2.INTER_NEAREST)
        with torch.inference_mode():
            tensor=torch.from_numpy(rgb).to(target).float()[None]/255
            prompt=LoadVisualPrompt().get_visuals(np.asarray([0]),(640,640),masks=visual[None]).to(target)[None]
            embeddings.append(model.model.get_visual_pe(tensor,prompt))
        names.append(f'{ref["kind"]}_{ref["type_id"]}_{ref["resource"]}')
        sources.append(dict(key=f'{ref["kind"]}:{ref["type_id"]}',image=str(file),
                            sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    if not embeddings:
        raise ValueError('No valid native references')
    model.set_classes(names,torch.cat(embeddings,dim=1))
    model.save_prompt_embeddings(output/'profile.npz')
    (output/'manifest.json').write_text(json.dumps(dict(weights=str(weights),training=False,
        method='Existing YOLOE visual encoder; fixed reference masks, no gradient updates',
        weights_sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),classes=names,sources=sources),indent=2)+'\n')
    print(json.dumps(dict(classes=len(names),profile=str(output/'profile.npz'),training=False)),flush=True)


def evaluate(weights,frames,output,reference=None,device='0',profile=None):
    if not weights.is_file():
        raise FileNotFoundError(weights)
    sdk=offline_sdk();YOLO,YOLOE=sdk.YOLO,sdk.YOLOE
    import torch
    torch.set_num_threads(2);cv2.setNumThreads(1)
    output.mkdir(parents=True,exist_ok=False)
    model=YOLOE(str(weights))if reference or profile else YOLO(str(weights))
    if profile:
        model.load_prompt_embeddings(profile)
    options=dict(device=device,imgsz=640,conf=.1,verbose=False,save=False)
    prompts=None
    if reference:
        prompts=json.loads((reference/'reference.json').read_text())
        model.predict(str(frames[0]),refer_image=str(reference/prompts['image']),
            visual_prompts=dict(bboxes=np.asarray(prompts['bboxes'],np.float32),
                                cls=np.asarray(prompts['cls'],np.int64)),**options)
    # Warmup includes first CUDA/context/model setup and is excluded from steady
    # inference percentiles. Wall time includes pre/post-processing and CPU copy.
    for _ in range(5):
        model.predict(str(frames[0]),**options)
    rows=[]
    for i,path in enumerate(frames):
        start=time.perf_counter();result=model.predict(str(path),**options)[0]
        detections=result.summary();elapsed=(time.perf_counter()-start)*1000
        row=dict(image=str(path),detections=detections,speed=result.speed,wall_ms=elapsed)
        rows.append(row)
        if i<12:
            result.save(str(output/f'{i:04d}.jpg'))
    report=dict(weights=str(weights),weights_sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),
        reference=str(reference)if reference else None,training=False,device=device,frames=len(rows),
        profile=str(profile)if profile else None,
        inference_options=options,warmup_frames=5,ultralytics_version=sdk.__version__,torch_version=torch.__version__,
        wall_ms=dict(median=float(np.median([r['wall_ms']for r in rows])),
                     p95=float(np.percentile([r['wall_ms']for r in rows],95))),
        classes=prompts['classes']if prompts else model.names)
    (output/'predictions.jsonl').write_text(''.join(json.dumps(row)+'\n'for row in rows))
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    ref=sub.add_parser('reference');ref.add_argument('--data',type=Path,required=True);ref.add_argument('--output',type=Path,required=True)
    asset=sub.add_parser('asset-profile');asset.add_argument('--weights',type=Path,required=True)
    asset.add_argument('--references',type=Path,required=True);asset.add_argument('--output',type=Path,required=True)
    asset.add_argument('--keys',nargs='+');asset.add_argument('--device',default='0')
    run=sub.add_parser('evaluate');run.add_argument('--weights',type=Path,required=True)
    run.add_argument('--frames',type=Path,nargs='+',required=True);run.add_argument('--output',type=Path,required=True)
    run.add_argument('--reference',type=Path);run.add_argument('--device',default='0')
    run.add_argument('--profile',type=Path)
    a=p.parse_args()
    if a.command=='reference':
        print(json.dumps(make_reference(a.data,a.output)))
    elif a.command=='asset-profile':
        asset_profile(a.weights,a.references,a.output,a.keys,a.device)
    else:
        if a.reference and a.profile:
            p.error('Use reference images or an existing prompt profile')
        evaluate(a.weights,a.frames,a.output,a.reference,a.device,a.profile)


if __name__=='__main__':
    main()
