"""Visible rope endpoints for an ongoing original air-down transfer."""
import math
import arena_motion as motion


def anchored_down_future(observation,seconds):
    """Return a bounded pixel forecast, or abstain to the existing profile.

    A newly measured compact body can lag the old action clock. Adding the
    profile's remaining displacement to that body must not move its final
    resting point away from the rope. Contact acknowledgement stays with the
    estimator; this function changes forecast geometry only.
    """
    from arena_vision import Box,rope_height,transition_speed,down_contact
    active=observation.get('motion');p=observation.get('player')
    if (p is None or not active or active['name']!='air_down'
            or active.get('contact_pending')or active.get('support_unconfirmed')
            or active.get('destination','rope')!='rope'or observation.get('rope')is None):
        return None
    elapsed=observation['time']-active['started']
    if elapsed<motion.transfer_delay('air_down',active):return None
    surface=rope_height(observation);future=rope_height(observation,seconds)
    if surface is None or future is None:return None
    scale=observation.get('scale_px',41.)
    sw=observation.get('stand_w',p.w);sh=observation.get('stand_h',p.h)
    speed=transition_speed(active)*scale;vx=observation.get('vx',0.)
    values=(seconds,elapsed,surface,future,scale,sw,sh,speed,vx,p.x,p.y,p.w,p.h)
    if not all(math.isfinite(v)for v in values)or min(scale,sw,sh,p.w,p.h,speed)<=0 or seconds<0:
        return None
    compact=p.h<=.5*sh
    if not compact and not down_contact(observation,active):return None
    if seconds==0:return p
    if not compact:
        # A branch which already reached contact follows the visible surface
        # until the existing duration/contact code ends its action ledger.
        return Box(p.x+vx*seconds,p.y+future-surface,p.w,p.h)
    target=future+.75*scale;cy=p.center[1]+speed*seconds
    arrived=min(p.center[1],cy)<=target<=max(p.center[1],cy)
    w,h=(sw,sh)if arrived else(p.w,p.h)
    cx=p.center[0]+vx*seconds+(motion.DATA['stand_offset_x']*scale if arrived else 0.)
    return Box(cx-w/2,(target if arrived else cy)-h/2,w,h)
