"""Optional stock YOLO pose points and conservative reticle target intervals."""
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import time


def normalized_box(box):
    x,y,w,h=box.x,box.y,box.w,box.h
    if not all(math.isfinite(v)for v in(x,y,w,h))or min(w,h)<=0:
        raise ValueError('Reticle box must be finite and positive')
    if h<w and y<=56:y,h=y+h-w,w
    elif h<w and y+h>=359:h=w
    return x,y,w,h


def rectangle_iou(a,b):
    w=max(0,min(a[2],b[2])-max(a[0],b[0]))
    h=max(0,min(a[3],b[3])-max(a[1],b[1]));area=w*h
    return area/max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


def refine_point_cue(cue,predictions):
    """Attach a point; preserve the proposal, phase and ordering on rejection."""
    reason='unconfirmed_phase';chosen=None;evidence={};box=cue['box']
    try:x,y,w,h=normalized_box(box)
    except (ValueError,AttributeError,TypeError,OverflowError):
        reason='invalid_box'
    else:
        if cue['phase']in('aim','locked'):
            reason='no_compatible_point';eligible=[];bounds=[box.x,box.y,box.x+box.w,box.y+box.h]
            for pred in predictions:
                if not all(math.isfinite(v)for v in(pred['confidence'],*pred['box'],*pred['point'])):continue
                if pred['phase']!=cue['phase']or pred['confidence']<.8 or pred['point'][2]<.8:continue
                point=pred['point'][:2];distance=math.dist(point,(x+w/2,y+h/2))
                overlap=rectangle_iou(pred['box'],bounds)
                if distance>8 or overlap<.3 or not(0<=point[0]<=640 and 55<=point[1]<=360):continue
                eligible.append((distance,-pred['confidence'],pred,overlap))
            eligible.sort(key=lambda p:p[:2])
            if eligible:
                first=eligible[0]
                others=[p for p in eligible[1:]if math.dist(p[2]['point'][:2],first[2]['point'][:2])>=3]
                if others and others[0][0]-first[0]<3:reason='ambiguous_points'
                else:
                    chosen=list(map(float,first[2]['point'][:2]));reason=None
                    evidence=dict(confidence=first[2]['confidence'],visibility=first[2]['point'][2],
                                  distance=first[0],iou=first[3],phase=first[2]['phase'])
    return dict(cue,center_refinement=dict(version=1,space='screen_640x360',center=chosen,
                reason=reason,evidence=dict(source='stock_yolo26n_pose',**evidence)))


def point_y(cue,camera_y):
    """Read only the optional pixel point; malformed evidence keeps the box."""
    baseline=cue['box'].center[1]-camera_y;field=cue.get('center_refinement')
    if (not isinstance(field,dict)or field.get('version')!=1
            or field.get('space')!='screen_640x360'or field.get('reason')is not None):return baseline
    center=field.get('center')
    if not isinstance(center,(tuple,list))or len(center)!=2:return baseline
    if any(isinstance(v,bool)or not isinstance(v,(int,float))or not math.isfinite(v)for v in center):return baseline
    if not(0<=center[0]<=640 and 0<=center[1]<=360):return baseline
    return center[1]-camera_y


def remember_point_interval(clock,baseline,point):
    """Parallel rolling medians retain the original target on either side."""
    if not all(math.isfinite(v)for v in(baseline,point)):return
    clock['point_low_samples']=(clock.get('point_low_samples',[])+[min(baseline,point)])[-3:]
    clock['point_high_samples']=(clock.get('point_high_samples',[])+[max(baseline,point)])[-3:]


def target_envelope(clock,base_height):
    """Original flight matching stays untouched; no smaller hazard is returned."""
    target=clock['target_y']
    if clock.get('attack_id')is not None:return target,base_height
    low=clock.get('point_low_samples');high=clock.get('point_high_samples')
    if not low or not high or not all(math.isfinite(v)for v in(*low,*high)):return target,base_height
    a=min(target,median(low));b=max(target,median(high))
    return (a+b)/2,base_height+b-a


class BambooPointRefiner:
    """Explicit optional model, warmed before capture; pixels and cues only."""
    def __init__(self,weights):
        import cv2
        import numpy as np
        import torch
        from arena_yolo import offline_sdk
        weights=Path(weights);profile_path=weights.parent.parent/'profile.json'
        profile=json.loads(profile_path.read_text())
        if (profile.get('task')!='pose'or profile.get('crop_px')!=64
                or profile.get('imgsz')not in(96,192)or profile.get('kpt_shape')!=[1,3]
                or profile.get('classes')!=['aim','locked']):
            raise ValueError('Expected a reviewed stock one-point reticle pose profile')
        torch.set_num_threads(2);self.model=offline_sdk().YOLO(str(weights))
        if self.model.task!='pose'or list(self.model.names.values())!=profile['classes']:
            raise ValueError('Reticle pose checkpoint/profile mismatch')
        self.options=dict(device=0,imgsz=profile['imgsz'],conf=.1,verbose=False,quantize=32)
        self.dummy=np.full((64,64,3),114,np.uint8)
        for count in(1,2,4,8,16,32):self.model.predict([self.dummy]*count,**self.options)
        self.info=dict(weights=str(weights),sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),
            profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),crop_px=64,
            imgsz=profile['imgsz'],batch_chunk=32,quantize=32,point_selection='phase_agreement_and_unique_nearby_point',
            geometry='Parallel target interval must retain the original bbox target; not a phase override')
        self.last_ms=0.;self.last_stats={}

    def refine(self,bgr,cues):
        import cv2
        import numpy as np
        if not isinstance(bgr,np.ndarray)or bgr.shape!=(360,640,3)or bgr.dtype!=np.uint8:
            raise ValueError('Reticle pose requires a 640x360 uint8 BGR image')
        begin=time.perf_counter();indices=[];crops=[];predictions={}
        for i,cue in enumerate(cues):
            if cue.get('motion_kind')!='bamboo':continue
            predictions[i]=[]
            try:normalized_box(cue['box'])
            except (ValueError,AttributeError,TypeError,OverflowError):continue
            indices.append(i);crops.append(cv2.getRectSubPix(bgr,(64,64),tuple(map(float,cue['box'].center))))
        for start in range(0,len(crops),32):
            batch=crops[start:start+32];count=len(batch);padded=1<<(count-1).bit_length()
            results=self.model.predict(batch+[self.dummy]*(padded-count),**self.options)[:count]
            for index,result in zip(indices[start:start+32],results):
                origin=np.array(cues[index]['box'].center)-31.5
                if result.boxes is None or result.keypoints is None:continue
                for box,cls,conf,point in zip(result.boxes.xyxy.cpu().numpy(),result.boxes.cls.cpu().numpy(),
                        result.boxes.conf.cpu().numpy(),result.keypoints.data.cpu().numpy()):
                    predictions[index].append(dict(box=(box+np.tile(origin,2)).tolist(),
                        phase=self.model.names[int(cls)],confidence=float(conf),
                        point=[float(point[0,0]+origin[0]),float(point[0,1]+origin[1]),float(point[0,2])]))
        output=[refine_point_cue(cue,predictions[i])if i in predictions else cue for i,cue in enumerate(cues)]
        self.last_ms=(time.perf_counter()-begin)*1000
        self.last_stats=dict(rois=len(crops),accepted=sum(c['center_refinement']['reason']is None
            for i,c in enumerate(output)if i in predictions),wall_ms=self.last_ms)
        return output
