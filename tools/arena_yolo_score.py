#!/usr/bin/env python3
"""Score the fine-tuned standard detector on whole, native-only episodes."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from arena_yolo import offline_sdk
from arena_yolo_data import NAMES,STATE_NAMES,annotations


def iou(a,b):
    left=max(a[0],b[0]);top=max(a[1],b[1]);right=min(a[2],b[2]);bottom=min(a[3],b[3])
    intersection=max(0,right-left)*max(0,bottom-top)
    area=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/max(1e-6,area)


def match_boxes(truth,prediction,parent=False):
    def family(cls):return 2 if parent and cls in (6,7)else cls
    pairs=[]
    for gi,(cls,gt)in enumerate(truth):
        for pi,(pc,box,_)in enumerate(prediction):
            overlap=iou(gt,box)
            if family(cls)==family(pc)and overlap>=.5:pairs.append((overlap,gi,pi))
    used_gt=set();used_pred=set();matched=[]
    for _,gi,pi in sorted(pairs,reverse=True):
        if gi not in used_gt and pi not in used_pred:
            used_gt.add(gi);used_pred.add(pi);matched.append((gi,pi))
    return matched


def score(weights,episodes,output,stride=3):
    sdk=offline_sdk();import torch
    torch.set_num_threads(2);cv2.setNumThreads(1);output.mkdir(parents=True,exist_ok=False)
    model=sdk.YOLO(str(weights));names=list(model.names.values())
    if names not in (NAMES,STATE_NAMES):
        raise ValueError('This scorer requires an arena detector class schema')
    options=dict(device=0,imgsz=640,conf=.25,verbose=False,quantize=16,max_det=100)
    for _ in range(5):model.predict(np.zeros((360,640,3),np.uint8),**options)
    counts={i:Counter()for i in range(len(names))};rows=[];times=[]
    spatial=Counter();confusion=Counter();illustrated=Counter()
    for folder in episodes:
        labels=[json.loads(line)for line in(folder/'labels.jsonl').open()]
        for row in labels[::stride]:
            truth=annotations(row,names==STATE_NAMES);image=cv2.imread(str(folder/row['image']))
            begin=time.perf_counter();prediction=model.predict(image,**options)[0]
            boxes=prediction.boxes.data.cpu().numpy();times.append((time.perf_counter()-begin)*1000)
            visible=[]
            for *box,confidence,cls in boxes:
                box=list(map(float,box))
                cx=(box[0]+box[2])/2;cy=(box[1]+box[3])/2
                if cy<55 or(cy>275 and(cx<135 or cx>515)):
                    continue
                visible.append((int(cls),box,float(confidence)))
            for cls,box in truth:counts[cls]['targets']+=1
            for cls,box,conf in visible:counts[cls]['predictions']+=1
            matches=match_boxes(truth,visible)
            for gi,pi in matches:counts[truth[gi][0]]['matched']+=1
            gt=[r for r in truth if r[0]>0];pr=[r for r in visible if r[0]>0]
            grouped=match_boxes(gt,pr,parent=True)
            spatial.update(targets=len(gt),predictions=len(pr),matched=len(grouped))
            for gi,pi in grouped:
                if gt[gi][0]in(2,6,7):
                    confusion[names[gt[gi][0]]+' -> '+names[pr[pi][0]]]+=1
            rows.append(dict(episode=str(folder),image=row['image'],truth=truth,
                             predictions=visible,matched=len(matches)))
            classes={cls for cls,_ in truth}
            if any(illustrated[cls]<2 for cls in classes):
                prediction.save(str(output/f'{len(rows):04d}.jpg'))
                illustrated.update(classes)
    def summarize(counter):
        result=dict(counter)
        result.update(precision=counter['matched']/max(1,counter['predictions']),
                      recall=counter['matched']/max(1,counter['targets']))
        return result
    hazards=sum((c for i,c in counts.items()if i>0),Counter())
    report=dict(checkpoint=str(weights),sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),
        episodes=[str(p)for p in episodes],frames=len(rows),threshold=.25,iou_threshold=.5,
        per_class={names[i]:summarize(c)for i,c in counts.items()},hazards=summarize(hazards),
        spatial_hazards=summarize(spatial),flying_state_confusion=dict(confusion),
        wall_ms=dict(median=float(np.median(times)),p95=float(np.percentile(times,95))),
        target='native collider envelopes; visibility filtering; no synthetic evaluation images')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'predictions.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in rows))
    print(json.dumps(report),flush=True);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--weights',type=Path,required=True)
    p.add_argument('--episodes',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--stride',type=int,default=3);a=p.parse_args();score(a.weights,a.episodes,a.output,a.stride)
