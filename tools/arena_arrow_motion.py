"""Pixel arrow roots, native penetration geometry and motion hypotheses.

Fire-arrow priors are calibration hypotheses. Native states/IDs/parameters are
never inputs; visible static ground and subsequent pixels correct each track.
"""
from collections import deque
from dataclasses import dataclass,field,replace
import math
import numpy as np
from arena_vision import Track,Box
from arena_object_motion import PRIORS
from arena_projection import SCALE
from arena_oriented import bounds
from arena_support import height


def restore_tail(detection,segments):
    """Recover the offscreen tail only when visible ground rules out insertion."""
    if detection.quad is None or max(x for x,y in detection.quad)<638:return
    from arena_object_support import object_support
    floor=object_support(segments,detection)
    if floor is None or floor['segment'].get('kind')!='platform'or detection.box.y+detection.box.h>=floor['y']-6:return
    unit,length,width=body_axis(detection.quad);full=PRIORS['arrow']['body_length']*SCALE
    if length>=full:return
    center=np.array(detection.box.center);front=center-unit*length/2;tail=front+unit*full
    normal=np.array([-unit[1],unit[0]])*max(width,PRIORS['arrow']['body_width']*SCALE)/2
    quad=tuple(tuple(map(float,p))for p in(front-normal,tail-normal,tail+normal,front+normal))
    detection.quad=quad;detection.box=Box(*bounds(quad));detection.geometry_restored=True


def body_axis(quad):
    q=np.asarray(quad,float);edges=(q[1]-q[0],q[2]-q[1]);edge=max(edges,key=lambda e:float(e@e))
    length=float(np.linalg.norm(edge));unit=edge/max(1e-6,length)
    if unit[0]<0:unit=-unit  # Calibrated incoming fire arrow: tail faces right.
    width=float(np.linalg.norm(min(edges,key=lambda e:float(e@e))))
    return unit,length,width


def velocity_prior(detection,scene_vx=None):
    if detection.quad is None:return None
    unit,_,_=body_axis(detection.quad)
    if abs(unit[0])<.2:return None
    speed=-PRIORS['arrow']['horizontal_speed_prior']*SCALE
    return speed+(scene_vx if scene_vx is not None else -10*SCALE),float(speed*unit[1]/unit[0])


@dataclass(frozen=True)
class ArrowState:
    x:float
    y:float
    vx:float
    vy:float
    ay:float
    angle:float
    depth:float
    grounded:bool=False
    impact_vx:float=0.
    predicted_contact:bool=False


def free_state(state,t,scene_vx):
    angle=state.angle
    world_vx=state.vx-scene_vx
    if abs(world_vx)>30:
        a=math.atan2(-state.vy,-world_vx);b=math.atan2(-(state.vy+state.ay*t),-world_vx)
        angle+=(b-a+math.pi)%(2*math.pi)-math.pi
    return replace(state,x=state.x+state.vx*t,y=state.y+state.vy*t+.5*state.ay*t*t,
                   vy=state.vy+state.ay*t,angle=angle)


def penetration(state,floor,t=0.):
    if floor is None or floor.get('kind')!='platform':return None
    y=height(floor,state.x,t)
    if y is None:return None
    sine=-math.sin(state.angle)
    return max(0.,(state.y-y)/sine)if sine>.05 else 0.


def propagate(state,seconds,floor,scene_vx):
    if state.grounded:
        vx=floor.get('vx',scene_vx)if floor else scene_vx;vy=floor.get('vy',0.)if floor else 0.
        return replace(state,x=state.x+vx*seconds,y=state.y+vy*seconds,vx=vx,vy=vy,ay=0.)
    end=free_state(state,seconds,scene_vx)
    if floor is None or floor.get('kind')!='platform':return end
    start_depth=penetration(state,floor);end_depth=penetration(end,floor,seconds)
    if start_depth is not None and start_depth<state.depth and end_depth is not None and end_depth<state.depth and state.ay>=0:
        return end
    previous=0.;hit=None
    steps=(0.,seconds)if end_depth is not None and end_depth>=state.depth else tuple(seconds*i/6 for i in range(7))
    for t in steps:
        moving=free_state(state,float(t),scene_vx);depth=penetration(moving,floor,float(t))
        if depth is not None and depth>=state.depth:
            lo,hi=previous,float(t)
            for _ in range(7):
                mid=(lo+hi)/2;p=penetration(free_state(state,mid,scene_vx),floor,mid)
                if p is not None and p>=state.depth:hi=mid
                else:lo=mid
            hit=hi;break
        previous=float(t)
    if hit is None:return end
    impact=free_state(state,hit,scene_vx);surface=height(floor,impact.x,hit)
    # Original ShootIntoGround retains X, clamps root Y at the selected random
    # penetration depth, freezes rotation and stops native flight movement.
    y=surface+impact.depth*max(0.,-math.sin(impact.angle))
    return replace(impact,x=impact.x+floor['vx']*(seconds-hit),y=y+floor['vy']*(seconds-hit),
                   vx=floor['vx'],vy=floor['vy'],ay=0.,grounded=True,
                   impact_vx=impact.vx,predicted_contact=True)


def state_quad(state,length,width,floor):
    unit=np.array([math.cos(state.angle),math.sin(state.angle)]);normal=np.array([-unit[1],unit[0]])
    p=penetration(state,floor);p=min(length,max(0.,p or 0.))
    root=np.array([state.x,state.y]);front=root+unit*p;tail=root+unit*length
    return tuple(tuple(map(float,point))for point in
                 (front-normal*width/2,tail-normal*width/2,tail+normal*width/2,front+normal*width/2))


@dataclass
class ArrowTrack(Track):
    models:tuple=()
    root_history:deque=field(default_factory=lambda:deque(maxlen=8))
    body_length:float=PRIORS['arrow']['body_length']*SCALE
    body_width:float=PRIORS['arrow']['body_width']*SCALE
    arrow_fit_error:float|None=None
    scene_vx:float=-10*SCALE
    last_floor_seen:float=-1e9
    _forecast_cache:dict=field(default_factory=dict,repr=False,compare=False)

    def local_floor(self):
        if self.floor_segment is None:return None
        floor=dict(self.floor_segment)
        for key in('a','b'):floor[key]=(floor[key][0]-self.reference[0],floor[key][1]-self.reference[1])
        return floor

    def update(self,detection,stamp,player,support_y=None):
        old_floor=self.floor_segment;old_reference=self.reference;old_seen=self.seen
        super().update(detection,stamp,player,support_y)
        if self.floor_segment is not None:self.last_floor_seen=stamp
        elif old_floor is not None and old_floor.get('kind')=='platform'and stamp-self.last_floor_seen<=.12:
            # Keep this arrow's previously observed static impact plane through
            # a short detector miss. This never creates player support or fills
            # a gap; finite endpoints and the original observation age remain.
            floor=dict(old_floor);dt=stamp-old_seen
            for key in('a','b'):
                floor[key]=(floor[key][0]+floor['vx']*dt+player[0]-old_reference[0],
                            floor[key][1]+floor['vy']*dt+player[1]-old_reference[1])
            self.floor_segment=floor
        self._forecast_cache={}
        self.models=();self.sine_count=0
        if detection.quad is None:return
        if max(x for x,y in detection.quad)>=638 and not detection.geometry_restored:
            self.root_history.clear();return
        unit,length,width=body_axis(detection.quad)
        self.body_width=max(PRIORS['arrow']['body_width']*SCALE,width)
        # UpdateCollider keeps the tail at root + originalLength while cutting
        # its front. This recovers the same root before and during penetration.
        cx,cy=self.box.center;root=np.array([cx-player[0],cy-player[1]])-unit*(self.body_length-length/2)
        self.root_history.append((stamp,*map(float,root)))
        if detection.scene_velocity_x is not None:self.scene_vx=detection.scene_velocity_x
        samples=np.asarray(self.root_history)
        if len(samples)<3 or samples[-1,0]-samples[0,0]<.035:return
        floor=self.local_floor();angle=math.atan2(float(unit[1]),float(unit[0]))
        geometry_state=ArrowState(float(root[0]),float(root[1]),0.,0.,0.,angle,0.)
        observed_penetration=penetration(geometry_state,floor)
        # Original collider cutting marks the flight/impact transition. A fit
        # spanning the earlier flight must not mask the new stopped root.
        if observed_penetration is not None and observed_penetration>0:samples=samples[-3:]
        t=samples[:,0]-stamp;design=np.column_stack((np.ones(len(t)),t));weights=np.exp(t/.12)
        fitx,_,_,_=np.linalg.lstsq(design*weights[:,None],samples[:,1]*weights,rcond=None)
        vx=float(fitx[1]);ys=samples[:,2];prior=PRIORS['arrow'];accelerations=[0.,prior['gravity_prior']*prior['velocity_gain']*SCALE]
        if len(samples)>=5 and -t[0]>=.12:
            quadratic=np.column_stack((np.ones(len(t)),t,t*t/2))
            fit,_,_,_=np.linalg.lstsq(quadratic*weights[:,None],ys*weights,rcond=None)
            if 0<=fit[2]<=15000:accelerations.append(float(fit[2]))
        choices=[]
        for i,acceleration in enumerate(accelerations):
            fit,_,_,_=np.linalg.lstsq(design*weights[:,None],(ys-.5*acceleration*t*t)*weights,rcond=None)
            error=float(np.sqrt(np.mean((design@fit+.5*acceleration*t*t-ys)**2)))
            choices.append((error+(.5 if i>=2 else 0.),error,float(fit[1]),acceleration))
        best=min(c[0]for c in choices);self.arrow_fit_error=min(c[1]for c in choices)
        models=[]
        minimum_depth=prior['penetration_depth'][0]*SCALE
        maximum_depth=prior['penetration_depth'][-1]*SCALE
        if observed_penetration is not None and minimum_depth<=observed_penetration<=maximum_depth+.2*SCALE:
            # The unknown original random depth can already have stopped this
            # arrow. Retain that causal alternative immediately, alongside any
            # still-flying hypothesis, rather than waiting for a long average.
            models.append(replace(geometry_state,vx=floor['vx'],vy=floor['vy'],depth=observed_penetration,grounded=True))
        if self.arrow_fit_error>4:
            if not models:return
            if abs(unit[0])>=.2:
                flight_vx=-prior['horizontal_speed_prior']*SCALE
                models.append(ArrowState(float(root[0]),float(root[1]),flight_vx+self.scene_vx,
                              flight_vx*float(unit[1]/unit[0]),accelerations[1],angle,maximum_depth))
            self.models=tuple(models);self.quad=None;return
        for score,error,vy,acceleration in choices:
            if score>best+.7:continue
            initial=ArrowState(float(root[0]),float(root[1]),vx,vy,acceleration,angle,0.)
            p=penetration(initial,floor)
            grounded=bool(p is not None and p>.2*SCALE and abs(vx-floor['vx'])<80 and abs(vy-floor['vy'])<60)
            depths=[p]if grounded else([d*SCALE for d in prior['penetration_depth']]if floor is not None and floor.get('kind')=='platform'else[prior['penetration_depth'][0]*SCALE])
            for depth in depths:models.append(replace(initial,depth=depth,grounded=grounded))
        self.models=tuple(models);self.vx=vx;self.vy=float(np.mean([m.vy for m in models]))
        # A single oriented rectangle cannot encode several roots/depths.
        # Both existing planners consume the resulting conservative AABB.
        self.quad=None

    def forecast(self,seconds):
        if seconds in self._forecast_cache:return self._forecast_cache[seconds]
        floor=self.local_floor();end_floor=None if floor is None else dict(floor)
        if end_floor is not None:
            for key in('a','b'):end_floor[key]=(floor[key][0]+floor['vx']*seconds,floor[key][1]+floor['vy']*seconds)
        states=tuple(propagate(m,seconds,floor,self.scene_vx)for m in self.models);lo_x=lo_y=math.inf;hi_x=hi_y=-math.inf
        for state in states:
            ux,uy=math.cos(state.angle),math.sin(state.angle)
            p=min(self.body_length,max(0.,penetration(state,end_floor)or 0.))
            cx=state.x+ux*(self.body_length+p)/2;cy=state.y+uy*(self.body_length+p)/2
            hw=(abs(ux)*(self.body_length-p)+abs(uy)*self.body_width)/2
            hh=(abs(uy)*(self.body_length-p)+abs(ux)*self.body_width)/2
            pad=abs(state.impact_vx-self.scene_vx)*PRIORS['arrow']['contact_tick_seconds']if state.predicted_contact else 0.
            lo_x=min(lo_x,cx-hw-pad);hi_x=max(hi_x,cx+hw+pad);lo_y=min(lo_y,cy-hh);hi_y=max(hi_y,cy+hh)
        result=Box(lo_x+self.reference[0],lo_y+self.reference[1],hi_x-lo_x,hi_y-lo_y),states
        self._forecast_cache[seconds]=result
        return result

    def future(self,seconds):
        return self.forecast(seconds)[0]if self.models else super().future(seconds)

    def at(self,seconds):
        if not self.models:return super().at(seconds)
        box,states=self.forecast(seconds);floor=None if self.floor_segment is None else dict(self.floor_segment)
        if floor is not None:
            for key in('a','b'):floor[key]=(floor[key][0]+floor['vx']*seconds,floor[key][1]+floor['vy']*seconds)
        return replace(self,box=box,models=states,quad=None,floor_segment=floor,_forecast_cache={},
                       vx=float(np.mean([m.vx for m in states])),vy=float(np.mean([m.vy for m in states])))
