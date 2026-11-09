#!/usr/bin/env python3
"""Score native physical quads, resource identity and visible support separately."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from arena_yolo import offline_sdk
from arena_yolo_obb_data import targets


def polygon_iou(a,b):
    a=cv2.convexHull(np.asarray(a,np.float32));b=cv2.convexHull(np.asarray(b,np.float32))
    intersection,_=cv2.intersectConvexConvex(a,b)
    return intersection/max(1e-6,cv2.contourArea(a)+cv2.contourArea(b)-intersection)


def match(truth,prediction,classes,mode='class'):
    def key(cls):
        c=classes[cls]
        if mode=='class':return cls
        if mode=='resource':
            return(c['kind'],c['resource'])if c.get('resource')else(c['kind'],c.get('motion_kind'),c['shape'])
        if mode=='geometry':return c['kind']if c['kind']!='hazard'else'hazard'
        raise ValueError(mode)
    pairs=[]
    for i,(c,a)in enumerate(truth):
        for j,(d,b,_)in enumerate(prediction):
            if key(c)==key(d):
                overlap=polygon_iou(a,b)
                if overlap>=.5:pairs.append((overlap,i,j))
    used_t=set();used_p=set();result=[]
    for _,i,j in sorted(pairs,reverse=True):
        if i not in used_t and j not in used_p:
            used_t.add(i);used_p.add(j);result.append((i,j))
    return result


def summarize(counter):
    return dict(counter,precision=counter['matched']/max(1,counter['predictions']),
                recall=counter['matched']/max(1,counter['targets']))


def score(weights,profile_path,episodes,output,stride=1):
    profile=json.loads(profile_path.read_text());classes=profile['classes']
    output.mkdir(parents=True,exist_ok=False);cv2.setNumThreads(1)
    import torch
    torch.set_num_threads(2)
    model=offline_sdk().YOLO(str(weights))
    if model.task!='obb'or list(model.names.values())!=[c['name']for c in classes]:
        raise ValueError('Checkpoint and native resource profile differ')
    options=dict(device=0,imgsz=640,conf=.25,quantize=16,verbose=False,max_det=150)
    for _ in range(5):model.predict(np.zeros((360,640,3),np.uint8),**options)
    counts={i:Counter()for i in range(len(classes))};modes={m:Counter()for m in('resource','geometry')}
    groups={k:Counter()for k in('player','hazard','cue','rope','platform','floating_platform')}
    times=[];frames=0
    with(output/'predictions.jsonl').open('w')as predictions:
        for episode in episodes:
            rows=[json.loads(s)for s in(episode/'labels.jsonl').open()]
            for row in rows[::stride]:
                truth,_=targets(row,profile);pixels=cv2.imread(str(episode/row['image']))
                begin=time.perf_counter();result=model.predict(pixels,**options)[0]
                quads=result.obb.xyxyxyxy.cpu().numpy();conf=result.obb.conf.cpu().numpy();ids=result.obb.cls.cpu().numpy()
                times.append((time.perf_counter()-begin)*1000)
                predicted=[]
                for c,q,s in zip(ids,quads,conf):
                    x,y=q.mean(0)
                    if y<55 or(y>275 and(x<135 or x>515)):continue
                    predicted.append((int(c),q.tolist(),float(s)))
                strict=match(truth,predicted,classes)
                for c,q in truth:
                    counts[c]['targets']+=1;groups[classes[c]['kind']]['targets']+=1
                for c,q,s in predicted:
                    counts[c]['predictions']+=1;groups[classes[c]['kind']]['predictions']+=1
                for i,j in strict:
                    c=truth[i][0];counts[c]['matched']+=1;groups[classes[c]['kind']]['matched']+=1
                for mode in modes:
                    hazards=[t for t in truth if classes[t[0]]['kind']=='hazard']
                    p=[t for t in predicted if classes[t[0]]['kind']=='hazard']
                    modes[mode].update(targets=len(hazards),predictions=len(p),matched=len(match(hazards,p,classes,mode)))
                predictions.write(json.dumps(dict(episode=str(episode),image=row['image'],truth=truth,
                                                  predictions=predicted,matched=len(strict)))+'\n')
                if frames<8:result.save(str(output/f'{frames:04d}.jpg'))
                frames+=1
    report=dict(frames=frames,episodes=[str(p)for p in episodes],checkpoint=str(weights),
                sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                confidence=.25,polygon_iou=.5,per_class={classes[i]['name']:summarize(c)for i,c in counts.items()if c},
                strict_groups={k:summarize(c)for k,c in groups.items()},
                hazards_ignoring_phase=summarize(modes['resource']),spatial_hazards=summarize(modes['geometry']),
                wall_ms=dict(median=float(np.median(times)),p95=float(np.percentile(times,95))),
                scope='Native gameplay-plane OBBs; spatial matches alone do not prove correct resource/phase/shape or successful control')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items()if k!='per_class'}),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in('weights','profile','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--episodes',type=Path,nargs='+',required=True);p.add_argument('--stride',type=int,default=1)
    a=p.parse_args();score(a.weights,a.profile,a.episodes,a.output,a.stride)
