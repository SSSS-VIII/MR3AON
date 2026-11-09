#!/usr/bin/env python3
"""Compare held-out YOLO predictions with native collider annotations.

This evaluates center/family association, not visual-box mAP: native damage
colliders and visible silhouettes have different extents by design.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import math
from arena_vision_dataset import objects


def resource_name(name):
    return name.split('(Clone)',1)[0].lower()


def family(name):
    name=name.lower()
    if 'spider'in name:
        return 'spider'
    if 'pinball'in name:
        return 'pinball'
    if 'bat'in name or 'crow'in name:
        return 'flying'
    return name


def audit(predictions,datasets):
    report=json.loads((predictions/'report.json').read_text());names=report['classes']
    if isinstance(names,list):
        names={str(i):n for i,n in enumerate(names)}
    lookup={}
    for folder in datasets:
        for line in(folder/'labels.jsonl').open():
            row=json.loads(line);lookup[str((folder/row['image']).resolve())]=row
    counts=Counter();errors=[]
    for line in(predictions/'predictions.jsonl').open():
        result=json.loads(line);row=lookup[str(Path(result['image']).resolve())]
        truth=objects(row,True);counts['native_targets']+=len(truth);counts['frames']+=1;pairs=[]
        for i,detection in enumerate(result['detections']):
            name=names[str(detection['class'])];box=detection['box']
            if not name.startswith('enemies_'):
                counts['other_class_predictions']+=1
                continue
            if not (85<(box['x1']+box['x2'])/2<615 and 65<(box['y1']+box['y2'])/2<330):
                continue
            counts['enemy_predictions']+=1
            name=name.split('_',2)[2]
            for identity,(obj,actual) in truth.items():
                x,y=actual.center
                distance=math.hypot((box['x1']+box['x2'])/2-x,(box['y1']+box['y2'])/2-y)
                correct_family=family(name)==family(resource_name(obj['name']))
                bounded=(box['x2']-box['x1']<max(50,actual.w*3)
                         and box['y2']-box['y1']<max(50,actual.h*3))
                if distance<25 and bounded and correct_family:
                    exact=name.lower()==resource_name(obj['name'])
                    pairs.append((distance,i,identity,exact))
        used=set();matched=set()
        for distance,i,identity,exact in sorted(pairs):
            if i not in used and identity not in matched:
                used.add(i);matched.add(identity);errors.append(distance)
                counts['family_matches']+=1;counts['exact_resource_matches']+=int(exact)
    result=dict(counts=counts,family_recall=counts['family_matches']/max(1,counts['native_targets']),
        enemy_precision=counts['family_matches']/max(1,counts['enemy_predictions']),
        definition='Family-correct center within25px and box dimensions below3x native collider envelope. Not visual mAP.',
        limitations='Active native colliders in gameplay ROI; no item ground truth, visibility alpha or full-state activation labels.')
    (predictions/'native-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--predictions',type=Path,required=True)
    p.add_argument('--datasets',type=Path,nargs='+',required=True);a=p.parse_args()
    print(json.dumps(audit(a.predictions,a.datasets)))
