"""Bounded visual initialization of an unusually strong observed rebound."""
import math
import numpy as np
from arena_object_motion import DATA


def refresh_fast_rebound(track,scale):
    """Use a measured reversal while a fresh ascending arc is too short to fit.

    The old impulse is contradicted by a much faster observed ascent. Require
    a preceding descent near the visible floor; never initialize from an
    arbitrary three-point arc, a missing floor or changing floor height.
    """
    if not track.pinball_fast_rebound or track.kind!='pinball':return False
    if (track.floor_y is None or not math.isfinite(track.floor_y)
            or not math.isfinite(track.floor_vy)or abs(track.floor_vy)>1
            or track.confidence<.7):return False
    samples=np.asarray(track.history,float)[-10:]
    if samples.ndim!=2 or samples.shape[1]!=3 or len(samples)<3 or not np.isfinite(samples).all():return False
    times=samples[:,0];ys=samples[:,2];steps=np.diff(times)
    if np.any(steps<=0)or steps[-1]>.1:return False
    slopes=np.diff(ys)/steps;start=0
    for k in range(1,len(slopes)):
        if slopes[k]<-40 and slopes[k]<slopes[k-1]-180:start=k+1
    if not start or len(samples)-start>=3 or slopes[start-2]<=0:return False
    prior=DATA['complete_gale_prior']if track.source_pinball_prior else DATA
    impulse=prior['rebound_speed']*scale
    if slopes[-1]>=-1.5*impulse:return False
    peak=ys[start-1]+track.reference[1]
    tolerance=4+max(abs(slopes[start-2]),impulse)*.02
    if abs(peak-track.floor_y)>tolerance:return False
    gravity=prior['accelerated_up']*scale
    velocity=float(slopes[-1]+.5*gravity*steps[-1])
    if velocity>=-impulse:return False
    track.vy=velocity;track.gravity_up=gravity;track.gravity_down=prior['accelerated_down']*scale
    track.rebound_speed=math.sqrt(velocity**2+2*gravity*max(0,track.floor_y-track.box.center[1]))
    track.ballistic=True
    return True
