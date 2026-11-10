"""Classical bouncing-body model; source priors, corrected by visual tracks."""
import math
import json
from pathlib import Path
import numpy as np

PRIORS=json.loads((Path(__file__).resolve().parents[1]/'arena/vision-object-priors.json').read_text())
DATA=PRIORS['pinball']
CROW=PRIORS['straight_crow']


def configure_crow(track,detection,stamp):
    phase=detection.attack_phase
    previous=track.attack_phase
    track.attack_phase=phase
    if phase=='ready':
        if track.ready_started is None or stamp-track.ready_started>.65:
            # A newly observed transition occurred between this image and the
            # preceding one. Use the interval midpoint, not the later exposure.
            gap=stamp-track.history[-2][0]if len(track.history)>1 else 0.
            track.ready_started=stamp-min(.05,max(0,gap/2))
            track.rush_target_w=track.box.w*CROW['collision_scale']
            track.rush_target_h=track.box.h*CROW['collision_scale']
        track.ready_remaining=max(0,CROW['ready_seconds']-(stamp-track.ready_started))
        track.rush_scale_remaining=CROW['scale_seconds']
    elif phase=='rush':
        track.ready_remaining=0.
        track.rush_target_w=max(track.box.w,track.rush_target_w)
        track.rush_target_h=max(track.box.h,track.rush_target_h)
        track.rush_scale_remaining=CROW['scale_seconds']
    if track.adaptive_rush_speed:
        if phase!='rush'or previous!='rush':
            track.rush_history.clear();track.rush_fit_velocity=None
        if phase=='rush':
            # Absolute image positions avoid treating an own flip's capsule
            # offset as a change in the enemy's rush speed.
            track.rush_history.append((stamp,track.box.center[0]))
            if len(track.rush_history)>=3:
                data=np.asarray(track.rush_history);times=data[:,0]-stamp
                if -times[0]>=.04:
                    design=np.column_stack((np.ones(len(times)),times))
                    fit,_,_,_=np.linalg.lstsq(design,data[:,1],rcond=None)
                    residual=float(np.sqrt(np.mean((design@fit-data[:,1])**2)))
                    track.rush_fit_velocity=float(fit[1])if residual<2 and -2400<fit[1]<-600 else None
                    if track.rush_fit_velocity is not None:track.rush_velocity=track.rush_fit_velocity


def crow_geometry(track,seconds,scale):
    from arena_vision import Box
    ready=max(0,track.ready_remaining)if track.attack_phase=='ready'else 0.
    moving=max(0,seconds-ready)
    velocity=(track.rush_velocity if track.rush_velocity is not None else
              (CROW['world_rush_speed']-CROW['reference_run_speed'])*scale)
    growth=min(1,moving/max(1e-9,track.rush_scale_remaining))
    w=track.box.w+(max(track.rush_target_w,track.box.w)-track.box.w)*growth
    h=track.box.h+(max(track.rush_target_h,track.box.h)-track.box.h)*growth
    x,y=track.box.center
    return Box(x+velocity*moving-w/2,y+track.vy*seconds-h/2,w,h)


def fit_ballistic(track,scale):
    samples=np.asarray(track.history)[-10:]
    if len(samples)<4:
        return
    t=samples[:,0]-samples[-1,0];ys=samples[:,2]
    slopes=np.diff(ys)/np.diff(t)
    start=0
    for k in range(1,len(slopes)):
        if slopes[k]<-40 and slopes[k]<slopes[k-1]-180:
            start=k+1
    if start:
        t=t[start:];ys=ys[start:]
    if len(t)<3 or t[-1]-t[0]<.035:
        return
    acceleration=DATA['accelerated_up'if slopes[-1]<0 else'accelerated_down']*scale
    design=np.column_stack((np.ones(len(t)),t))
    fit,_,_,_=np.linalg.lstsq(design,ys-.5*acceleration*t*t,rcond=None)
    error=float(np.sqrt(np.mean((design@fit+.5*acceleration*t*t-ys)**2)))
    # A short near-apex arc is indistinguishable from a stationary object.
    # Reject the class gravity prior only after a longer, consistently straight
    # observed window contradicts it; do not change a known bounce on one frame.
    evidence=np.asarray(track.history)
    evidence=evidence[evidence[:,0]>=evidence[-1,0]-.4]
    contradicted=False
    if len(evidence)>=6 and evidence[-1,0]-evidence[0,0]>=.3:
        et=evidence[:,0]-evidence[-1,0];ey=evidence[:,2]
        linear_design=np.column_stack((np.ones(len(et)),et))
        linear,_,_,_=np.linalg.lstsq(linear_design,ey,rcond=None)
        curve=.5*acceleration*et*et
        gravity,_,_,_=np.linalg.lstsq(linear_design,ey-curve,rcond=None)
        linear_error=float(np.sqrt(np.mean((linear_design@linear-ey)**2)))
        gravity_error=float(np.sqrt(np.mean((linear_design@gravity+curve-ey)**2)))
        contradicted=linear_error<.8 and gravity_error>2*max(.05,linear_error)
    if error>4 or contradicted:
        return
    track.vy=float(fit[1]);track.ballistic=True
    track.gravity_up=DATA['accelerated_up']*scale
    track.gravity_down=DATA['accelerated_down']*scale
    segment=track.floor_segment
    track.floor_vy=0.
    if segment:
        a,b=segment['a'],segment['b'];slope=(b[1]-a[1])/(b[0]-a[0])
        track.floor_vy=segment['vy']+slope*(track.vx-segment['vx'])
    if not track.rebound_speed:
        track.rebound_speed=DATA['rebound_speed']*scale
    if track.vy<-60 and track.floor_y is not None and abs(track.floor_vy)<1:
        height=max(0,track.floor_y-track.box.center[1])
        # Ascent energy estimates the individual rebound impulse without a
        # privileged parameter query or needing to have seen the floor contact.
        energy=math.sqrt(track.vy**2+2*track.gravity_up*height)
        track.rebound_speed=.7*track.rebound_speed+.3*energy


def floor_horizon(track):
    segment=track.floor_segment
    if segment is None:return math.inf
    relative=track.vx-segment['vx'];x=track.box.center[0]
    if relative<0:return math.inf if segment.get('left_clipped',False)else max(0,(x-segment['a'][0])/-relative)
    if relative>0:return math.inf if segment.get('right_clipped',False)else max(0,(segment['b'][0]-x)/relative)
    return math.inf


def pinball_state(track,seconds):
    known=min(seconds,floor_horizon(track))if track.floor_y is not None else 0.
    y,velocity=bounce_state(track.box.center[1],track.vy,known,
        floor=track.floor_y if track.floor_y is not None else math.inf,
        floor_velocity=track.floor_vy,gravity_up=track.gravity_up,
        gravity_down=track.gravity_down,rebound=track.rebound_speed)
    if known<seconds:
        y,velocity=bounce_state(y,velocity,seconds-known,floor=math.inf,
            gravity_up=track.gravity_up,gravity_down=track.gravity_down,rebound=track.rebound_speed)
    return y,velocity


def bounce_state(y,velocity,seconds,*,floor,gravity_up,gravity_down,rebound,floor_velocity=0.):
    """Advance constant-gravity arcs with an instantaneous floor impulse."""
    remaining=max(0,seconds);y=min(y,floor)
    for _ in range(16):
        if remaining<=1e-8:
            break
        if velocity<0:
            until=-velocity/gravity_up;step=min(remaining,until)
            y+=velocity*step+.5*gravity_up*step*step
            velocity+=gravity_up*step;remaining-=step
            floor+=floor_velocity*step
            if step>=until-1e-9:velocity=0.
        else:
            distance=max(0,floor-y)
            relative=velocity-floor_velocity
            until=(-relative+math.sqrt(relative**2+2*gravity_down*distance))/gravity_down
            step=min(remaining,until)
            y+=velocity*step+.5*gravity_down*step*step
            velocity+=gravity_down*step;remaining-=step
            floor+=floor_velocity*step
            if step>=until-1e-9:
                y=floor;velocity=-max(1,rebound)
    return y,velocity


def bounce_y(y,velocity,seconds,**parameters):
    return bounce_state(y,velocity,seconds,**parameters)[0]
