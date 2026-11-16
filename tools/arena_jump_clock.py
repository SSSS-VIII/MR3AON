"""Optional first-jump clock fit from actual pixels and independent camera flow.

The original motion curve is calibrated offline. This module has no model,
client, native state, board identity, future observation or input transport.
"""
from collections import deque
import math
import numpy as np
import arena_motion as motion


class JumpClockFeedback:
    CAMERA_SOURCES=frozenset(('support_track','support_line_overlap','ground_patch'))

    def __init__(self):
        self.history=deque(maxlen=16)
        self.last_stamp=None

    def reject(self,reason,*,clear=True):
        if clear:self.history.clear()
        return dict(applied=False,reason=reason)

    def estimate(self,observation):
        stamp=observation['time']
        if not math.isfinite(stamp):return self.reject('invalid_time')
        if self.last_stamp is not None and stamp<=self.last_stamp:
            return self.reject('repeated_or_old_exposure',clear=False)
        self.last_stamp=stamp
        p=observation.get('player')
        if p is None or observation.get('player_predicted',False):return self.reject('no_actual_body')
        scale=observation.get('scale_px',0.)
        reference=observation.get('camera_reference_y')
        if (reference is None or not all(math.isfinite(v)for v in (scale,reference,p.y,p.h))
                or scale<=0 or p.h<=0):return self.reject('invalid_geometry')
        if observation.get('camera_motion_source')not in self.CAMERA_SOURCES:
            return self.reject('camera_not_independent')
        segments=observation.get('rope_segments')or[observation.get('rope_segment')]
        if (observation.get('rope')is None or observation.get('terrain')is not None
                or not segments or not all(self.flat(s)for s in segments)):
            return self.reject('not_flat_rope')
        active=observation.get('motion')or{}
        kind=active.get('name')
        anchor=active.get('clock_anchor_started',active.get('started'))
        self.history.append(dict(t=stamp,value=(reference-p.center[1])/scale,height=p.h/scale,
                                 kind=kind,anchor=anchor,phase=observation.get('phase')))
        if kind!='jump1':return self.reject('not_first_jump',clear=False)
        if anchor is None or not math.isfinite(anchor):return self.reject('invalid_anchor')
        if not 0<=stamp-anchor<=.25:return self.reject('outside_entry_window',clear=False)
        past=[s for s in self.history if stamp-.16<=s['t']<=stamp and s['t']>=anchor-.04
              and (s['kind']=='jump1'and s['anchor']==anchor
                   or s['kind']is None and s['phase']=='rope_above'and s['t']<=anchor)]
        if len(past)<3 or past[-1]['t']-past[0]['t']<.05:
            return self.reject('short_actual_history',clear=False)
        if not all(s['height']<=.8*motion.DATA['stand_height']for s in past[-3:]):
            return self.reject('compact_pose_unconfirmed',clear=False)

        # Every fitted age lies within the reviewed entry curve. Evaluate all
        # phase candidates together; this is the same piecewise interpolation
        # as motion.point, without hundreds of Python calls per visible frame.
        shifts=np.arange(-50,51,dtype=float)/1000
        points=np.asarray(motion.DATA['profiles']['jump1']['points'],dtype=float)
        ages=np.maximum(0,np.array([s['t']-anchor for s in past])[:,None]+shifts[None,:])
        shape=ages.shape
        root=np.interp(ages.ravel(),points[:,0],points[:,2]).reshape(shape)
        offset=np.interp(ages.ravel(),points[:,0],points[:,3]).reshape(shape)
        height=np.interp(ages.ravel(),points[:,0],points[:,5]).reshape(shape)
        residual=np.array([s['value']for s in past])[:,None]-root-offset
        residual-=residual.mean(axis=0)
        height_error=np.array([s['height']for s in past])[:,None]-height
        losses=np.mean(residual**2+.25*height_error**2,axis=0)*scale**2
        index=int(np.argmin(losses));shift=float(shifts[index])
        return dict(applied=True,reason='actual_compact_pose_history',shift_seconds=shift,
                    anchor_started=anchor,samples=len(past),span_seconds=past[-1]['t']-past[0]['t'],
                    original_error_px2=float(losses[50]),fitted_error_px2=float(losses[index]),
                    at_bound=abs(shift)==.05)

    @staticmethod
    def flat(segment):
        if not segment:return False
        try:
            a,b=segment['a'],segment['b'];dx=b[0]-a[0];dy=b[1]-a[1]
            return all(math.isfinite(v)for v in (*a,*b))and dx>=4 and abs(dy)<=1 and abs(dy)<=.01*dx
        except (KeyError,TypeError,ValueError):return False
