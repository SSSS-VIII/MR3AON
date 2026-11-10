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
from arena_obb_detector import support_segment

PHYSICAL_KINDS={'hazard','slice_target'}

def match_support_lines(truth,prediction,classes,tolerance=6.):
    """Score physical centerlines separately from thin-band polygon IoU."""
    candidates=[]
    for i,(c,q)in enumerate(truth):
        if classes[c]['shape']!='segment':continue
        a,b=map(np.asarray,support_segment(q))
        for j,(d,r,_)in enumerate(prediction):
            if classes[d]['kind']!=classes[c]['kind']:continue
            x,y=map(np.asarray,support_segment(r))
            lo=max(a[0],x[0]);hi=min(b[0],y[0])
            lengths=(b[0]-a[0],y[0]-x[0])
            if min(lengths)<4 or hi-lo<.5*max(lengths):continue
            xs=np.array([lo,hi]);ay=a[1]+(b[1]-a[1])*(xs-a[0])/lengths[0]
            by=x[1]+(y[1]-x[1])*(xs-x[0])/lengths[1]
            error=float(np.max(abs(ay-by)))
            if error<=tolerance:candidates.append((error,i,j))
    used_t=set();used_p=set();pairs=[]
    for error,i,j in sorted(candidates):
        if i not in used_t and j not in used_p:
            used_t.add(i);used_p.add(j);pairs.append((i,j,error))
    return pairs


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
        if mode=='physical':return 'physical'if c['kind']in PHYSICAL_KINDS else c['kind']
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


def resource_recalls(native_truth,truth,prediction,native_classes,classes):
    """Recall by original truth resource even when model classes are shared.

    A shared detector does not predict original resource identity, so no
    per-resource precision or recognition accuracy may be inferred here.
    """
    selected=[i for i,(c,q)in enumerate(truth)if classes[c]['kind']in PHYSICAL_KINDS]
    t=[truth[i]for i in selected];p=[r for r in prediction if classes[r[0]]['kind']in PHYSICAL_KINDS]
    counts={}
    for index in selected:
        meta=native_classes[native_truth[index][0]]
        counts.setdefault(meta['resource'],Counter())['targets']+=1
    for i,j in match(t,p,classes,'physical'):
        resource=native_classes[native_truth[selected[i]][0]]['resource'];counter=counts[resource]
        counter['matched']+=1
        if classes[t[i][0]]['shape']==classes[p[j][0]]['shape']:counter['shape_matched']+=1
        if t[i][0]==p[j][0]:counter['class_matched']+=1
    return counts


def interaction_confusions(truth,prediction,classes,policy_confidence=.8):
    truth=[r for r in truth if classes[r[0]]['kind']in PHYSICAL_KINDS]
    prediction=[r for r in prediction if classes[r[0]]['kind']in PHYSICAL_KINDS]
    result=Counter(hazard_targets=sum(classes[c]['kind']=='hazard'for c,q in truth),
                   slice_targets=sum(classes[c]['kind']=='slice_target'for c,q in truth),
                   policy_target_predictions=sum(classes[c]['kind']=='slice_target'and s>=policy_confidence for c,q,s in prediction))
    matched_policy=set()
    for i,j in match(truth,prediction,classes,'physical'):
        a=classes[truth[i][0]]['kind'];b=classes[prediction[j][0]]['kind']
        result[a+'->'+b]+=1
        if a=='hazard'and b=='slice_target'and prediction[j][2]>=policy_confidence:
            result['policy_hazard_as_target']+=1
        if b=='slice_target'and prediction[j][2]>=policy_confidence:
            matched_policy.add(j)
            if a=='slice_target':result['policy_slice_as_target']+=1
    result['policy_unmatched_targets']=result['policy_target_predictions']-len(matched_policy)
    return result


def centerline_truth(row,profile,truth):
    native=profile.get('native_targets',profile)
    if native.get('support_band_px',4)==4:return truth
    original,_=targets(row,dict(native,support_band_px=4))
    return([(profile['class_mapping'][c],q)for c,q in original]
           if profile.get('taxonomy')=='physics'else original)


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
    for c in classes:groups.setdefault(c['kind'],Counter())
    support_counts={k:Counter()for k in('rope','platform','floating_platform')};line_errors=[]
    per_resource={};native_profile=profile.get('native_targets',profile)
    uncovered=Counter()
    interactions=Counter();physical=Counter()
    times=[];frames=0
    with(output/'predictions.jsonl').open('w')as predictions:
        for episode in episodes:
            rows=[json.loads(s)for s in(episode/'labels.jsonl').open()]
            for row in rows[::stride]:
                native_truth,stats=targets(row,native_profile)
                uncovered.update({k:v for k,v in stats.items()if k.startswith('unbound_visible')or k=='unconfigured_visible_targets'})
                truth=([(profile['class_mapping'][c],q)for c,q in native_truth]
                       if profile.get('taxonomy')=='physics'else native_truth)
                pixels=cv2.imread(str(episode/row['image']))
                begin=time.perf_counter();result=model.predict(pixels,**options)[0]
                quads=result.obb.xyxyxyxy.cpu().numpy();conf=result.obb.conf.cpu().numpy();ids=result.obb.cls.cpu().numpy()
                times.append((time.perf_counter()-begin)*1000)
                predicted=[]
                for c,q,s in zip(ids,quads,conf):
                    x,y=q.mean(0)
                    if y<55 or(y>275 and(x<135 or x>515)):continue
                    predicted.append((int(c),q.tolist(),float(s)))
                strict=match(truth,predicted,classes)
                interactions.update(interaction_confusions(truth,predicted,classes,profile.get('target_policy_confidence',.8)))
                physical_t=[r for r in truth if classes[r[0]]['kind']in PHYSICAL_KINDS]
                physical_p=[r for r in predicted if classes[r[0]]['kind']in PHYSICAL_KINDS]
                physical.update(targets=len(physical_t),predictions=len(physical_p),
                                matched=len(match(physical_t,physical_p,classes,'physical')))
                for resource,counter in resource_recalls(native_truth,truth,predicted,native_profile['classes'],classes).items():
                    per_resource.setdefault(resource,Counter()).update(counter)
                line_truth=centerline_truth(row,profile,truth)
                for c,q in line_truth:
                    if classes[c]['kind']in support_counts:support_counts[classes[c]['kind']]['targets']+=1
                for c,q,s in predicted:
                    if classes[c]['kind']in support_counts:support_counts[classes[c]['kind']]['predictions']+=1
                for i,j,error in match_support_lines(line_truth,predicted,classes):
                    support_counts[classes[line_truth[i][0]]['kind']]['matched']+=1;line_errors.append(error)
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
                ontology_coverage_accepted=not bool(uncovered),uncovered_native_geometry=dict(uncovered),
                sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                confidence=.25,polygon_iou=.5,per_class={classes[i]['name']:summarize(c)for i,c in counts.items()if c},
                interaction_confusions=dict(interactions),target_policy_confidence=profile.get('target_policy_confidence',.8),
                spatial_physical_objects=summarize(physical),
                strict_groups={k:summarize(c)for k,c in groups.items()},
                support_centerlines={k:summarize(c)for k,c in support_counts.items()},
                original_resource_recall={k:dict(c,spatial_recall=c['matched']/max(1,c['targets']))
                                          for k,c in per_resource.items()},
                original_resource_scope='Truth-resource spatial recall only; shared model classes do not predict original resource identity',
                support_line_criteria=dict(max_y_error_px=6,overlap_fraction_of_longer=.5,reference_band_px=4,
                    matched_max_y_error_median=float(np.median(line_errors))if line_errors else None),
                support_supervision_band_px=native_profile.get('support_band_px',4),
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
