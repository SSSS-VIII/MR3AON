"""Visual reticle clocks and source-based projectile envelopes; no client IO.

Original EnemyFlyBamboo uses aimLockTime=.5, a further .5-second ready state,
then a 60-world-unit/second attack. Native 60Hz transition quantization adds up
to about .04 seconds. BambooCtrl and FlySpear have three-unit attack boxes;
their different collider centers are retained as a spawn-position interval.
"""
from dataclasses import dataclass,replace
from statistics import median
from arena_vision import Box,Detection,Track,Tracker
from arena_projection import SCALE
from arena_bamboo_point import point_y, remember_point_interval, target_envelope


@dataclass
class BambooForecast(Track):
    fire_earliest:float=0.
    fire_latest:float=0.
    spawn_left:float=0.
    spawn_right:float=0.
    projectile_width:float=3*SCALE
    projectile_height:float=.2*SCALE
    velocity_fast:float|None=None
    velocity_slow:float|None=None

    def future(self,seconds):
        stamp=self.seen+seconds
        fast=self.vx if self.velocity_fast is None else self.velocity_fast
        slow=self.vx if self.velocity_slow is None else self.velocity_slow
        left=self.spawn_left+fast*max(0,stamp-self.fire_earliest)-self.projectile_width/2
        right=self.spawn_right+slow*max(0,stamp-self.fire_latest)+self.projectile_width/2
        return Box(left,self.box.center[1]-self.projectile_height/2,
                   max(self.projectile_width,right-left),self.projectile_height)

    def at(self,seconds):
        return replace(self,box=self.future(seconds),seen=self.seen+seconds)


class BambooClocks:
    """Associate only visual reticles; native object IDs/states are not inputs."""
    def __init__(self):
        self.tracker=Tracker();self.clocks={}
        self.point_uncertainty=False

    def observe(self,cues,stamp,camera_y=0.):
        # Two phase logits can survive class-wise NMS at the same reticle.
        # Retain the strongest spatial prediction before temporal association.
        selected=[]
        for cue in sorted(cues,key=lambda c:(c['phase']in('aim','locked'),c['confidence']),reverse=True):
            if cue['phase']not in('aim','locked','uncertain')or cue['confidence']<.25:continue
            if any(abs(cue['box'].center[0]-s['box'].center[0])<8 and
                   abs(cue['box'].center[1]-s['box'].center[1])<8 for s in selected):continue
            selected.append(cue)
        tracks=self.tracker.update([Detection(c['box'],'bamboo_reticle',c['confidence'])for c in selected],
                                   stamp,(0.,camera_y))
        for track in tracks:
            if track.seen!=stamp or not selected:continue
            cue=min(selected,key=lambda c:abs(c['box'].center[0]-track.box.center[0])+
                    abs(c['box'].center[1]-track.box.center[1]))
            clock=self.clocks.setdefault(track.id,dict(last_seen=stamp,last_aim=None,
                first_lock=None,lock_count=0,fire=None,confidence=[],target_samples=[],target_y=track.box.center[1]-camera_y))
            clock['last_seen']=stamp
            clock['confidence']=(clock['confidence']+[cue['confidence']])[-8:]
            if cue['phase']=='locked':
                clock['target_samples']=(clock['target_samples']+[track.box.center[1]-camera_y])[-3:]
                clock['target_y']=median(clock['target_samples'])
                if self.point_uncertainty:
                    remember_point_interval(clock,track.box.center[1]-camera_y,point_y(cue,camera_y))
            if clock['fire']is not None:continue
            if cue['phase']=='aim':
                clock.update(last_aim=stamp,first_lock=None,lock_count=0,
                             target_y=track.box.center[1]-camera_y)
            elif cue['phase']=='locked':
                if clock['first_lock']is None:clock['first_lock']=stamp
                clock['lock_count']+=1
                if clock['lock_count']>=2 and track.observations>=3:
                    first=clock['first_lock'];aim=clock['last_aim']
                    # A first sighting already locked cannot supply its onset.
                    # Keep that uncertainty instead of restarting a full timer.
                    # Phase recognition can remain on the previous class for
                    # one exposure at a transition. Preserve that observation
                    # interval as timing uncertainty rather than claiming that
                    # the last 'aim' image proves locking had not started.
                    # Uncertain animation exposures can separate the last
                    # definite aim from the first definite lock by >150ms.
                    # Intersect that visual onset bound with the full unknown
                    # age interval; a gap is not a reason to discard the aim.
                    start=(max(first-1.04,aim-min(.06,max(.02,first-aim)))
                           if aim is not None else first-1.04)
                    clock.update(fire=(start+1.,first+1.04))
        self.clocks={k:v for k,v in self.clocks.items()if
                     (stamp<=v['fire'][1]+.35 if v['fire']else stamp-v['last_seen']<.25)}

    def forecasts(self,stamp,scene_vx,camera_y=0.):
        result=[]
        for identity,clock in self.clocks.items():
            if clock['fire']is None:continue
            lo,hi=clock['fire']
            if stamp>hi+.35:continue
            target,height=(target_envelope(clock,.2*SCALE) if self.point_uncertainty
                           else (clock['target_y'],.2*SCALE))
            y=target+camera_y
            # A full-width rope has no uncropped material endpoint. Missing
            # scroll evidence is not evidence that the camera stopped. Original
            # Gale positive block speeds are 9..20; include blocked motion 0.
            fast=-80*SCALE if scene_vx is None else -60*SCALE+scene_vx
            slow=-60*SCALE if scene_vx is None else fast
            t=BambooForecast(-2000000-identity,Box(700,y-height/2,3*SCALE,height),
                'bamboo_forecast',median(clock['confidence']),stamp,observations=3,
                vx=(fast+slow)/2,attack_phase='bamboo_locked',collider_shape='BoxCollider',
                projectile_height=height,fire_earliest=lo,fire_latest=hi,spawn_left=640+(2-.85)*SCALE,
                spawn_right=640+(2-.0677337646484375)*SCALE,velocity_fast=fast,velocity_slow=slow)
            t.box=t.future(0);result.append(t)
        return result
