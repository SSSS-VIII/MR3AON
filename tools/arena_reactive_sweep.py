"""Continuous collision checks for the reactive 40 ms action forecast.

Profile knots bound motion between decisions; action cadence, terrain-wall
cost and original motion priors remain unchanged.
"""
import math
import numpy as np
from arena_vision import Box, create_motion, constrain_ground_motion, root_foot_box
from arena_policy import collision_weight
from arena_oriented import transform, swept_capsules, is_box
import arena_motion as motion


def rectangle_quad(box):
    return np.array([[box.x,box.y],[box.x+box.w,box.y],
                     [box.x+box.w,box.y+box.h],[box.x,box.y+box.h]])


def segment_rectangle_distance_sq(a,b,half):
    """Exact segment/AABB distance, including zero-width horizontal/vertical cores."""
    a=np.asarray(a,float);b=np.asarray(b,float);half=np.asarray(half,float)
    delta=b-a;lo=0.;hi=1.
    for start,speed,extent in zip(a,delta,half):
        if abs(speed)<1e-12:
            if abs(start)>extent:lo,hi=1.,0.;break
        else:
            x,y=sorted(((-extent-start)/speed,(extent-start)/speed))
            lo=max(lo,x);hi=min(hi,y)
    if lo<=hi:return 0.
    distance=min(float(np.square(np.maximum(0,np.abs(p)-half)).sum())for p in(a,b))
    denominator=max(1e-30,float(delta@delta))
    for x in(-half[0],half[0]):
        for y in(-half[1],half[1]):
            point=np.array([x,y]);fraction=float(np.clip((point-a)@delta/denominator,0,1))
            distance=min(distance,float(np.square(a+fraction*delta-point).sum()))
    return distance


def swept_pair(before,after,old,new,*,shape='ellipse',old_quad=None,new_quad=None,
               angle=0.,margin=4.,curve_padding=(0.,0.),body_sizes=()):
    """Conservative continuous counterpart of the existing capsule predicates.

    Box contacts reuse the existing support-function hull sweep. Ellipse
    contacts preserve the old inflated-ellipse semantics, with BOTH body core
    axes. Each size maximum is conservative for changing native collider shape.
    """
    sizes=[(before.w,before.h),(after.w,after.h),*body_sizes]
    width=max(s[0]for s in sizes);height=max(s[1]for s in sizes)
    radius=max(min(w,h)/2 for w,h in sizes)
    core_x=max(max(0,(w-h)/2)for w,h in sizes)
    core_y=max(max(0,(h-w)/2)for w,h in sizes)
    pad_x,pad_y=curve_padding
    sagitta=0.
    if shape=='box' and angle:
        if old_quad is not None and new_quad is not None:
            extent=max(float(np.linalg.norm(q-np.asarray(q).mean(0),axis=1).max())
                       for q in(np.asarray(old_quad),np.asarray(new_quad)))
        else:extent=max(math.hypot(old.w,old.h),math.hypot(new.w,new.h))/2
        theta=abs(angle)
        sagitta=extent*(1-math.cos(theta/2))if theta<=2*math.pi else 2*extent
    # Sufficient separation of the relative swept AABBs, before any SAT
    # allocations. Covers translation, changing dimensions and arc padding.
    extents=(max(old.w,new.w)/2+radius+core_x+margin+pad_x+sagitta,
             max(old.h,new.h)/2+radius+core_y+margin+pad_y+sagitta)
    for a,b,extent in zip((x-y for x,y in zip(old.center,before.center)),
                          (x-y for x,y in zip(new.center,after.center)),extents):
        if min(a,b)>extent or max(a,b)<-extent:return False
    if shape=='box':
        old_quad=rectangle_quad(old)if old_quad is None else np.asarray(old_quad,float)
        new_quad=rectangle_quad(new)if new_quad is None else np.asarray(new_quad,float)
        # A horizontal -> vertical pose interval can have BOTH core axes.
        # Feeding its total width/height back as one capsule loses diagonal
        # support. Use a radius-only circle plus independent core margins.
        b=np.array([[*before.center,2*radius,2*radius]])
        a=np.array([[*after.center,2*radius,2*radius]])
        return bool(swept_capsules(b,a,old_quad[None],new_quad[None],
                                  margin+pad_x+core_x,margin+pad_y+core_y,sagitta)[0,0])
    radii=np.array([max(old.w,new.w)/2+radius+margin+pad_x,
                    max(old.h,new.h)/2+radius+margin+pad_y])
    if min(radii)<=0:raise ValueError('positive collider axes required')
    a=(np.array(old.center)-np.array(before.center))/radii
    b=(np.array(new.center)-np.array(after.center))/radii
    core=np.array([core_x,core_y])/radii
    return segment_rectangle_distance_sq(a,b,core)<=1.


def action_motion(obs,action):
    if action=='none':active=obs.get('motion');offset=-(obs['time']-active['started'])if active else 0.
    else:
        name=('jump2'if obs['jumps']>=1 else'jump1')if action=='jump'else action
        if action in('flip','escape'):name='rope_up'if obs['phase']=='rope_below'else'rope_down'
        active=create_motion(obs,name);offset=0.
    return active,offset


def action_knots(obs,action):
    """Original profile/transition times; not an arbitrary finer time grid."""
    active,offset=action_motion(obs,action)
    knots=[]
    if active:
        name=active['name'];profile=motion.DATA['profiles'].get(name,{})
        knots.extend(offset+p[0]for p in profile.get('points',[]))
        knots.extend(offset+p[0]for p in profile.get('root_extra_x',[]))
        duration=motion.duration(name,active)
        if math.isfinite(duration):knots.append(offset+duration)
        if name in('air_down','air_up'):knots.append(offset+motion.transfer_delay(name,active))
        if action=='escape':knots.extend(duration+p[0]for p in motion.DATA['profiles']['jump1']['points'])
    return knots


def player_smooth_padding(obs,action,start,end,after):
    """Only actual analytic pieces need acceleration bounds; flat ground = 0.

    Tabulated native profiles are piecewise linear and their original knots
    already enter the interval envelope. Bound their analytic tails/recovery,
    fallback freefall and falling off finite visual support separately.
    """
    scale=obs.get('scale_px',41.);span=end-start;pad=np.zeros(2)
    active,offset=action_motion(obs,action)
    name=active['name']if active else None
    if action=='escape' and active:
        duration=motion.duration(name,active)
        if end>duration:name='jump1';offset=duration
    profile=motion.DATA['profiles'].get(name,{})
    if profile.get('points') and end-offset>profile['points'][-1][0]:
        pad[1]=abs(profile.get('tail_acceleration',0.))*scale*span*span/8
    if name=='ground_recovery':
        prior=motion.DATA['profiles']['slide'];rate=math.log(prior['recovery_multiplier'])/prior['recovery_tick_seconds']
        pad[0]=abs(active.get('offset_carry_x',0))*scale*rate*rate*motion.recovery_factor(max(0,start-offset))*span*span/8
    if action=='none' and not active and obs['phase'] not in('ground','slide','rope_above','rope_below','unknown'):
        up,down=motion.air_accelerations(obs.get('jumps',0))
        pad[1]=max(up,down)*scale*span*span/8
    # The original finite-support functions append freefall only after leaving
    # connected visual support. Never add gravity on a supported flat segment.
    terrain=obs.get('terrain');selected=None;segments=[]
    ground_motion=name in('slide','ground_recovery')
    supported_none=action=='none' and not active and obs['phase']in('ground','slide','rope_above','rope_below','unknown')
    if ground_motion or supported_none:
        if terrain and terrain.get('source')=='neural_segments'and terrain.get('at_player'):
            segments=terrain['segments'];selected=next((s for s in segments if s['id']==terrain['selected_id']),None)
        elif supported_none and obs.get('rope_segment'):
            selected=obs['rope_segment'];segments=obs.get('rope_segments')or[selected]
        if selected:
            from arena_support import connected_height
            root_x=(after.center[0]-motion.point(name,end-offset,active)[0]*scale
                    if ground_motion else obs['player'].center[0]+obs.get('vx',0.)*end)
            if connected_height(segments,selected['id'],root_x,end)is None:
                pad[1]=max(pad[1],motion.DATA['fall_from_run']['gravity']*scale*span*span/8)
    return pad


def hazard_padding(track,start,end):
    """Known smooth-arc bound; rebound uses a conservative speed envelope."""
    span=end-start
    ax=abs(track.ax)if track.curve_count>=3 else 0.
    ay=abs(track.ay)if track.curve_count>=3 else 0.
    if track.sine_count>=2:ay=max(ay,math.hypot(track.sine_a,track.sine_b)*track.sine_frequency**2)
    padding=[ax*span*span/8,ay*span*span/8]
    if track.ballistic:
        from arena_object_motion import pinball_state
        va=pinball_state(track,start)[1];vb=pinball_state(track,end)[1]
        padding[1]=max(padding[1],max(track.gravity_up,track.gravity_down)*span*span/8)
        if va>0>vb:padding[1]=max(padding[1],max(abs(va),abs(vb),track.rebound_speed)*span/2)
    return padding


def reactive_risk(self,obs,action):
    objects=self._objects(obs)
    obs=dict(obs,blocking_faces=[dict(x=t.box.x,y=t.box.y,vx=t.vx,vy=t.vy,stamp=obs['time'])
                                for t in objects if t.kind=='terrain_wall'])
    previous=obs;lost_x=0.;hits={};wall_frames={};knots=action_knots(obs,action)
    for step in range(1,20):
        start=(step-1)*.04;end=step*.04
        before=previous['player'];old_lost=lost_x
        p=self._path(obs,action,end);base_x=p.x;p=Box(p.x+lost_x,p.y,p.w,p.h)
        state=self._path_state(obs,action,end,p);state=constrain_ground_motion(previous,state)
        p=state['player'];lost_x=p.x-base_x
        # Original profile knots give exact extrema of piecewise-linear
        # priors. Midpoint plus gravity bound also covers smooth freefall;
        # no added decision step or endpoint timing changes.
        samples=sorted({start,end,(start+end)/2,*[t for t in knots if start<t<end]})
        bodies=[]
        for t in samples:
            fraction=(t-start)/.04
            q=self._path(obs,action,t)
            q=Box(q.x+old_lost+(lost_x-old_lost)*fraction,q.y,q.w,q.h)
            if t==start:q=before
            if t==end:q=p
            bodies.append(q)
        body_pad=np.zeros(2)
        for t,q in zip(samples,bodies):
            fraction=(t-start)/.04
            chord=np.array(before.center)+(np.array(p.center)-before.center)*fraction
            body_pad=np.maximum(body_pad,np.abs(np.array(q.center)-chord))
        body_pad+=player_smooth_padding(obs,action,start,end,p)
        for track in objects:
            if track.id in hits and track.kind!='terrain_wall':continue
            new=self._hazard(track,end)
            if track.kind=='terrain_wall':
                foot=root_foot_box(state)
                collision=(abs(foot.center[0]-new.center[0])<new.w/2+
                           motion.DATA['blocking']['climb_distance']*obs.get('scale_px',41.)+4
                           and new.y-2<foot.center[1]<new.y+new.h+2)
                if collision:wall_frames[track.id]=wall_frames.get(track.id,0)+1
            else:
                old=self._hazard(track,start);pad=np.array(hazard_padding(track,start,end))+body_pad
                special=[.25,track.ready_remaining,track.ready_remaining+track.rush_scale_remaining]
                for t in [s for s in special if start<s<end]:
                    point=self._hazard(track,t);fraction=(t-start)/.04
                    chord=np.array(old.center)+(np.array(new.center)-old.center)*fraction
                    pad=np.maximum(pad,np.abs(np.array(point.center)-chord)+body_pad)
                oriented=track.quad is not None and track.collider_shape=='BoxCollider'
                oq=transform(track.quad,track.angular_velocity*start,old.center)if oriented else None
                nq=transform(track.quad,track.angular_velocity*end,new.center)if oriented else None
                collision=swept_pair(before,p,old,new,shape='box'if is_box(track)else'ellipse',
                                     old_quad=oq,new_quad=nq,angle=track.angular_velocity*.04 if oriented else 0.,
                                     curve_padding=pad,body_sizes=[(b.w,b.h)for b in bodies])
            if collision:hits.setdefault(track.id,(end,track))
        previous=state
    cost=sum(100*collision_weight(track)*(1+(.8-t)*2)for t,track in hits.values()if track.kind!='terrain_wall')
    cost+=sum(100*10*n*.04 for n in wall_frames.values())
    return cost,min((t for t,_ in hits.values()),default=10),hits
