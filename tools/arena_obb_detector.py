"""Standard YOLO OBB pixels -> collider quads and visible support segments."""
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from arena_yolo import offline_sdk
from arena_vision import Box,Detection,Perception,Tracker,player_future
from arena_oriented import bounds,rectangle
from arena_support import VisualSupports
from arena_projection import SCALE
import arena_motion as motion


def profile_path(weights):
    return Path(weights).parent.parent/'profile.json'


def support_segment(quad):
    """Midpoints of the short edges recover the supervised physical line."""
    q=np.asarray(quad,float)
    edges=np.roll(q,-1,axis=0)-q
    i=int(np.argmin(np.linalg.norm(edges[:2],axis=1)))
    a=(q[i]+q[(i+1)%4])/2;b=(q[(i+2)%4]+q[(i+3)%4])/2
    if a[0]>b[0]:a,b=b,a
    return tuple(map(float,a)),tuple(map(float,b))


def missing_role_prediction(observation,stamp,age):
    if not observation or observation.get('player')is None:return None,None
    predicted=player_future(observation,stamp-observation['time'])
    if age<.22:return predicted,'short_gap'
    active=observation.get('motion')
    # A submitted native jump can carry the role above the camera for longer
    # than the ordinary occlusion lease. Retain only that expected excursion;
    # an unexplained miss inside the playfield must still stop the actor.
    if (age<.65 and active and active['name'].startswith('jump')
            and predicted.y+predicted.h<70):return predicted,'expected_above_view'
    return None,None


def decode(quads,ids,scores,profile,player_x=180.):
    hazards=[];supports=[];cues=[];player=None;best=0
    for quad,cls,confidence in zip(quads,ids,scores):
        q=np.asarray(quad,float);meta=profile['classes'][int(cls)]
        if q.shape!=(4,2)or not np.isfinite(q).all():continue
        cx,cy=q.mean(0)
        if cy<55 or(cy>275 and(cx<135 or cx>515)):continue
        kind=meta['kind'];box=Box(*bounds(q));confidence=float(confidence)
        if kind=='player':
            dx=abs(cx-player_x);score=confidence*float(np.exp(-dx/80))
            if dx<80 and score>best:player=box;best=score
        elif kind in('rope','platform','floating_platform'):
            a,b=support_segment(q)
            if b[0]-a[0]>=4:
                supports.append(dict(kind=kind,a=a,b=b,confidence=confidence,
                    left_clipped=bool(q[:,0].min()<=3),right_clipped=bool(q[:,0].max()>=637)))
        elif kind=='cue':
            cues.append(dict(box=box,confidence=confidence,resource=meta.get('resource')))
        elif kind in('hazard','slice_target'):
            shape=meta['shape'];phase=meta.get('phase')
            motion_kind=meta.get('motion_kind')
            resource=meta.get('resource')
            if kind=='slice_target'and confidence<profile.get('target_policy_confidence',.8):
                # Low-confidence target predictions remain conservative obstacles.
                motion_kind='trap'
            if not motion_kind:
                family=profile.get('families',{}).get(resource,{})
                scripts=family.get('script_types',[])
                motion_kind=('eye_enemy'if family.get('straight_bat')or'EnemyCurveBat'in scripts else
                             'spider'if'EnemySpider'in scripts else'pinball'if'EnemyPinball'in scripts else'trap')
                if not family.get('straight_bat'):phase=None
            # A square OBB may rotate arbitrarily. Its enclosing AABB is not
            # the original sphere diameter; use the actual predicted sides.
            if shape=='SphereCollider':
                _,w,h,_=rectangle(q);diameter=(w+h)/2
                box=Box(float(cx-diameter/2),float(cy-diameter/2),diameter,diameter)
            hazards.append(Detection(box,motion_kind,confidence,phase=='rush',phase=='ready',phase,
                                     resource,shape,tuple(tuple(map(float,p))for p in q)))
    return player,hazards,supports,cues


class ObbDetector:
    def __init__(self,weights,confidence=.25):
        weights=Path(weights);self.profile=json.loads(profile_path(weights).read_text());self.confidence=confidence
        if self.profile.get('task')!='obb'or self.profile.get('geometry')!='gameplay_plane':
            raise ValueError('Expected a native gameplay-plane OBB profile')
        import torch
        torch.set_num_threads(2)
        self.model=offline_sdk().YOLO(str(weights))
        if self.model.task!='obb'or list(self.model.names.values())!=[c['name']for c in self.profile['classes']]:
            raise ValueError('OBB checkpoint and resource profile differ')
        self.sha256=hashlib.sha256(weights.read_bytes()).hexdigest()
        self.options=dict(device=0,imgsz=640,conf=confidence,verbose=False,quantize=16,max_det=150)
        for _ in range(6):self.model.predict(np.zeros((360,640,3),np.uint8),**self.options)
        self.player_x=180.;self.last_ms=0.

    def reset_tracking(self):
        self.player_x=180.

    def detect(self,rgb):
        begin=time.perf_counter()
        result=self.model.predict(cv2.cvtColor(rgb[:,:,:3],cv2.COLOR_RGB2BGR),**self.options)[0]
        obb=result.obb
        decoded=decode(obb.xyxyxyxy.cpu().numpy(),obb.cls.cpu().numpy(),obb.conf.cpu().numpy(),self.profile,self.player_x)
        if decoded[0]is not None:self.player_x=decoded[0].center[0]
        self.last_ms=(time.perf_counter()-begin)*1000
        return decoded


class ObbPerception(Perception):
    """Only pixels and committed own inputs enter this state estimator."""
    def __init__(self,detector):
        super().__init__();self.detector=detector;self.visual_role=True
        if hasattr(detector,'reset_tracking'):detector.reset_tracking()
        self.tracker=Tracker(adaptive=True,adaptive_rush_speed=True);self.supports=VisualSupports();self.last_seen_player=None
        self.rush_models={};self.rush_prior=None

    def observe(self,rgba,stamp):
        rgb=rgba[:,:,:3];player,detections,segments,cues=self.detector.detect(rgb)
        predicted=False;prediction_reason=None
        if player is not None:self.last_seen_player=stamp
        elif self.last_seen_player is not None:
            player,prediction_reason=missing_role_prediction(self.last_observation,stamp,stamp-self.last_seen_player)
            predicted=player is not None
        support=self.supports.observe(segments,player,stamp)
        if predicted:
            dy=support['tracking_reference'][1]-self.last_observation.get('camera_reference_y',0.)
            player=Box(player.x,player.y+dy,player.w,player.h)
        result=self._finish(rgb,stamp,player,detections,support_observation=support,player_observed=not predicted)
        observed_vx=result['vx']
        # With a reliable static-scene flow the forward-running root cannot
        # retreat faster than that scene. Crop jitter or a newly blocked runner
        # must not become an escape trajectory through the left of a wall.
        if support['scene_motion_observed']and support['scene_vx']<0:
            result['vx']=max(observed_vx,support['scene_vx'])
        for track in result['tracks']:
            if (track.rush_fit_velocity is not None and track.confidence>=.8
                    and track.box.x>5 and track.box.x+track.box.w<635):
                self.rush_models[track.id]=(track.seen,track.rush_fit_velocity)
        self.rush_models={k:v for k,v in self.rush_models.items()if stamp-v[0]<1.2}
        if self.rush_models:self.rush_prior=float(np.median([v[1]for v in self.rush_models.values()]))
        for track in result['tracks']:
            if track.attack_phase in('ready','rush')and track.rush_fit_velocity is None:
                track.rush_velocity=self.rush_prior
        result.update(scale_px=SCALE,stand_w=motion.DATA['stand_width']*SCALE,
                      stand_h=motion.DATA['stand_height']*SCALE,geometry='gameplay_plane',
                      detector='standard_yolo26n_obb',detector_ms=self.detector.last_ms,cues=cues,
                      observed_rush_velocity=self.rush_prior,
                      hazard_confidence=getattr(self.detector,'confidence',.25),
                      visible_supports=support['segments'],player_predicted=predicted,
                      player_prediction_reason=prediction_reason,
                      camera_reference_y=support['tracking_reference'][1],camera_velocity_y=support['camera_vy'],
                      scene_velocity_x=support['scene_vx'],scene_velocity_x_raw=support['scene_vx_raw'],
                      observed_player_velocity_x=observed_vx,
                      player_seen_age=None if self.last_seen_player is None else stamp-self.last_seen_player)
        return result
