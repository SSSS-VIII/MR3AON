"""Classical bouncing-body model; source priors, corrected by visual tracks."""
import math
import json
from pathlib import Path
import numpy as np

DATA=json.loads((Path(__file__).resolve().parents[1]/'arena/vision-object-priors.json').read_text())['pinball']


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
    if error>4:
        return
    track.vy=float(fit[1]);track.ballistic=True
    track.gravity_up=DATA['accelerated_up']*scale
    track.gravity_down=DATA['accelerated_down']*scale
    track.floor_y=track.reference[1]-track.box.h/2
    if not track.rebound_speed:
        track.rebound_speed=DATA['rebound_speed']*scale
    if track.vy<-60:
        height=max(0,track.floor_y-track.box.center[1])
        # Ascent energy estimates the individual rebound impulse without a
        # privileged parameter query or needing to have seen the floor contact.
        energy=math.sqrt(track.vy**2+2*track.gravity_up*height)
        track.rebound_speed=.7*track.rebound_speed+.3*energy


def bounce_state(y,velocity,seconds,*,floor,gravity_up,gravity_down,rebound):
    """Advance constant-gravity arcs with an instantaneous floor impulse."""
    remaining=max(0,seconds);y=min(y,floor)
    for _ in range(16):
        if remaining<=1e-8:
            break
        if velocity<0:
            until=-velocity/gravity_up;step=min(remaining,until)
            y+=velocity*step+.5*gravity_up*step*step
            velocity+=gravity_up*step;remaining-=step
            if step>=until-1e-9:velocity=0.
        else:
            distance=max(0,floor-y)
            until=(-velocity+math.sqrt(velocity**2+2*gravity_down*distance))/gravity_down
            step=min(remaining,until)
            y+=velocity*step+.5*gravity_down*step*step
            velocity+=gravity_down*step;remaining-=step
            if step>=until-1e-9:
                y=floor;velocity=-max(1,rebound)
    return y,velocity


def bounce_y(y,velocity,seconds,**parameters):
    return bounce_state(y,velocity,seconds,**parameters)[0]
