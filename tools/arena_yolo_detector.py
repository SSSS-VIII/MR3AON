"""Fine-tuned standard YOLO detector feeding visual tracking/state estimation."""
from pathlib import Path
import time
import json
import hashlib
import cv2
import numpy as np
from arena_yolo import offline_sdk
from arena_yolo_data import NAMES,STATE_NAMES
from arena_vision import Box,Detection,Perception,Tracker,player_future
from arena_projection import sphere_plane,capsule_plane,SCALE
import arena_motion as motion

KINDS={1:'spider',2:'eye_enemy',3:'pinball',4:'trap',5:'projectile',6:'eye_enemy',7:'eye_enemy'}
ROOT=Path(__file__).resolve().parents[1]
PROFILE=json.loads((ROOT/'arena/vision-detector.json').read_text())
DEFAULT_WEIGHTS=ROOT/PROFILE['weights']


class YoloDetector:
    def __init__(self,weights,confidence=.3):
        weights=Path(weights)
        if weights.resolve()==DEFAULT_WEIGHTS.resolve():
            if hashlib.sha256(weights.read_bytes()).hexdigest()!=PROFILE['sha256']:
                raise ValueError('Arena checkpoint differs from the reviewed profile')
        import torch
        torch.set_num_threads(2)
        self.model=offline_sdk().YOLO(str(weights));self.confidence=confidence;self.player_x=180.
        names=list(self.model.names.values())if isinstance(self.model.names,dict)else self.model.names
        if names not in (NAMES,STATE_NAMES):
            raise ValueError(f'Unexpected arena detector classes: {names}')
        self.state_classes=names==STATE_NAMES
        self.options=dict(device=0,imgsz=640,conf=confidence,verbose=False,quantize=16,max_det=100)
        dummy=np.zeros((360,640,3),np.uint8)
        for _ in range(6):self.model.predict(dummy,**self.options)
        self.last_ms=0

    def detect(self,rgb):
        start=time.perf_counter();bgr=cv2.cvtColor(rgb[:,:,:3],cv2.COLOR_RGB2BGR)
        result=self.model.predict(bgr,**self.options)[0]
        rows=result.boxes.data.cpu().numpy();hazards=[];player=None;best=0
        for x1,y1,x2,y2,confidence,cls in rows:
            box=Box(float(x1),float(y1),float(x2-x1),float(y2-y1));cls=int(cls)
            if cls==0:
                # Associate the role across frames. A fixed screen ROI loses
                # the original dragged/knockback pose; unrestricted top-score
                # selection can instead jump onto a distant enemy lookalike.
                dx=abs(box.center[0]-self.player_x)
                score=float(confidence)*float(np.exp(-dx/80))
                if dx<80 and score>best:
                    player=capsule_plane(box);best=score
                continue
            if box.center[1]<55 or box.center[1]>345:
                continue
            arming=cls==6
            if cls==2 and not self.state_classes:
                patch=rgb[max(0,int(y1)):min(360,int(y2)+1),max(0,int(x1)):min(640,int(x2)+1),:3]
                if patch.size:
                    r,g,b=[patch[:,:,i].astype(np.float32)for i in range(3)]
                    arming=float(((r>85)&(r>g*1.7)&(r>b*1.2)&(g<115)).mean())>.14
            if cls in (1,2,3,6,7):
                box=sphere_plane(box)
            phase=({2:'normal',6:'ready',7:'rush'}.get(cls))if self.state_classes else None
            hazards.append(Detection(box,KINDS[cls],float(confidence),cls==7,arming,phase))
        self.last_ms=(time.perf_counter()-start)*1000
        if player is not None:self.player_x=player.center[0]
        return player,hazards


class YoloPerception(Perception):
    """YOLO boxes plus existing support/state/temporal motion estimation.

No rule-based enemy proposals enter this path. Native role motion is a future
prior; it must not overwrite the current collider box measured by the detector.
"""
    def __init__(self,detector):
        super().__init__();self.detector=detector;self.visual_role=True;self.last_seen_player=None
        self.tracker=Tracker(adaptive=True)

    def observe(self,rgba,stamp):
        rgb=rgba[:,:,:3]
        gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(np.int16)
        contrast=np.zeros(gray.shape,np.uint8)
        contrast[7:-7]=((np.minimum(gray[:-14],gray[14:])-gray[7:-7])>18).astype(np.uint8)
        horizontal=cv2.morphologyEx(contrast,cv2.MORPH_OPEN,np.ones((1,70),np.uint8))
        counts=horizontal.sum(1);peaks=np.flatnonzero((counts>250)&(np.arange(360)>80)&(np.arange(360)<310))
        ropes=[]
        for group in np.split(peaks,np.flatnonzero(np.diff(peaks)>1)+1):
            if len(group)and len(group)<=10:
                ropes.append(float(np.average(group,weights=counts[group])))
        self.rope=min(ropes,key=lambda y:abs(y-(self.rope or 260)))if ropes else None
        player,detections=self.detector.detect(rgb)
        predicted=False
        if player is not None:
            self.last_seen_player=stamp
        elif self.last_seen_player is not None and stamp-self.last_seen_player<.22 and self.last_observation:
            player=player_future(self.last_observation,stamp-self.last_observation['time']);predicted=True
        result=self._finish(rgb,stamp,player,detections)
        result.update(scale_px=SCALE,stand_w=motion.DATA['stand_width']*SCALE,
                      stand_h=motion.DATA['stand_height']*SCALE,geometry='gameplay_plane')
        for track in result['tracks']:
            # The red appearance can persist after a dash begins. Measured
            # horizontal motion supplies attack state, not a board-time script.
            if (track.kind=='eye_enemy'and track.observations>=3 and track.vx<-750
                    and track.attack_phase!='ready'):
                track.active=True
        result.update(detector_ms=self.detector.last_ms,player_predicted=predicted,
                      detector='fine_tuned_yolo26n',player_seen_age=None if self.last_seen_player is None else stamp-self.last_seen_player)
        return result
