"""Visible line association and support state; no native state or color rules."""
from collections import deque
import numpy as np


def leading_ground_faces(segments,stamp):
    """Visible solid-ground entrances; floating surfaces and joined seams aren't walls.

    These faces are derived geometry, never extra detector/native enemy labels.
    A six-pixel top tolerance avoids penalising normal surface contact.
    """
    ground=[s for s in segments if s['kind']=='platform'and not s.get('left_clipped',False)and s.get('confidence',0)>=.25
            and (s['confidence']>=.7 or s.get('observations',0)>=3)]
    faces=[]
    for s in ground:
        x,y=s['a']
        if not 3<x<637 or s['b'][0]-x<8:continue
        joined=False
        for other in ground:
            if other is s or other['a'][0]>=x-4 or other['b'][0]<x-4:continue
            sy=height(other,min(x,other['b'][0]))
            if sy is not None and abs(sy-y)<=6:joined=True;break
        if joined:continue
        dt=max(0,stamp-s['stamp']);vx=s.get('vx',0);vy=s.get('vy',0)
        faces.append(dict(id=s['id'],x=x+vx*dt,y=y+vy*dt+6,vx=vx,vy=vy,
                          confidence=s['confidence']))
    return faces


def height(segment,x,seconds=0):
    dx=segment.get('vx',0)*seconds;dy=segment.get('vy',0)*seconds
    a,b=segment['a'],segment['b'];ax=a[0]+dx;bx=b[0]+dx
    if bx-ax<4:return None
    # A viewport cut is not a physical endpoint. Continue its observed tangent
    # for forecasts; interior gaps still have two explicit uncropped endpoints.
    if x<ax and not segment.get('left_clipped',False):return None
    if x>bx and not segment.get('right_clipped',False):return None
    return float(a[1]+dy+(b[1]-a[1])*(x-ax)/(bx-ax))


def landing_height(terrain,x,seconds,from_y):
    """Future visible surface below the current capsule center, if any."""
    values=[y for s in terrain.get('segments',[])if s['kind']!='rope'
            for y in[height(s,x,seconds)]if y is not None and y>=from_y-2]
    return min(values)if values else None


def describe_terrain(ground,selected,px,*,include_samples=True):
    y=height(selected,min(max(px,selected['a'][0]),selected['b'][0]))
    samples=[]
    for x in range(0,640,4)if include_samples else ():
        ys=[v for s in ground for v in[height(s,x)]if v is not None]
        value=min(ys,key=lambda v:abs(v-y))if ys else y
        samples.append((x,value-7,bool(ys)))
    edge=selected['b'][0]if not selected.get('right_clipped',selected['b'][0]>=637)else None
    ahead=[s['a'][0]for s in ground if edge is not None and s['a'][0]>edge+4]
    return dict(y=y-7,at_player=height(selected,px)is not None,edge=edge,
                landing=min(ahead)if ahead else None,speed=max(0,-selected['vx'])or None,
                samples=samples,segments=ground,selected_id=selected['id'],source='neural_segments')


def advance_terrain(terrain,seconds,px):
    future_y=connected_height(terrain['segments'],terrain['selected_id'],px,seconds)
    segments=[]
    for original in terrain['segments']:
        s=dict(original)
        for key in('a','b'):
            s[key]=(s[key][0]+s['vx']*seconds,s[key][1]+s['vy']*seconds)
        segments.append(s)
    selected=next(s for s in segments if s['id']==terrain['selected_id'])
    if future_y is not None:
        selected=min((s for s in segments if height(s,px)is not None),
                     key=lambda s:abs(height(s,px)-future_y))
    return describe_terrain(segments,selected,px,include_samples=False)


def connected_height(segments,selected_id,x,seconds=0):
    """Follow visible touching surfaces, without bridging a gap or a step."""
    reachable={selected_id};pending=[s for s in segments if s['id']==selected_id]
    while pending:
        previous=pending.pop()
        for s in segments:
            if s['id']in reachable or s['kind']!=previous['kind']:continue
            if min(np.linalg.norm(np.asarray(previous[a])-s[b])for a,b in [('a','b'),('b','a')])<=6:
                reachable.add(s['id']);pending.append(s)
    values=[y for s in segments if s['id']in reachable for y in[height(s,x,seconds)]if y is not None]
    return min(values)if values else None


def overlapping_static_camera_shift(current,previous,dx=None):
    """Recover camera Y through neural line splits/merges without track IDs.

    Compare overlapping material after this interval's measured X translation.
    A horizontal line also constrains Y without X evidence. Multiple parallel
    levels or inconsistent hypotheses are unknown, rather than a nearest match.
    """
    candidates=[]
    for new in current:
        if new['kind']not in('rope','platform')or new['confidence']<.7:continue
        na,nb=new['a'],new['b'];nw=nb[0]-na[0]
        if nw<64:continue
        ns=(nb[1]-na[1])/nw
        for old in previous:
            if old['kind']!=new['kind']or old['confidence']<.7:continue
            oa,ob=old['a'],old['b'];ow=ob[0]-oa[0]
            if ow<64 or not .006<=new['stamp']-old['stamp']<=.16:continue
            os=(ob[1]-oa[1])/ow
            if abs(ns-os)>.02:continue
            if dx is None and max(abs(ns),abs(os))>.002:continue
            shift_x=0. if dx is None else dx
            left=max(na[0],oa[0]+shift_x,0.)
            right=min(nb[0],ob[0]+shift_x,640.)
            if right-left<64:continue
            x=(left+right)/2
            shift=na[1]+ns*(x-na[0])-oa[1]-os*(x-shift_x-oa[0])
            if abs(shift)<=35:candidates.append((shift,right-left,left,right))
    if not candidates or max(c[0]for c in candidates)-min(c[0]for c in candidates)>3:return None
    # Duplicated pieces aren't independent votes. Require actual image coverage,
    # and use a length-weighted median only after every hypothesis agrees.
    intervals=sorted((c[2],c[3])for c in candidates);end=-1.;coverage=0.
    for left,right in intervals:
        coverage+=max(0.,right-max(left,end));end=max(end,right)
    if coverage<96:return None
    half=sum(c[1]for c in candidates)/2;weight=0.
    for shift,length,_,_ in sorted(candidates):
        weight+=length
        if weight>=half:return shift


class VisualSupports:
    def __init__(self,*,line_camera_recovery=False,texture_camera_recovery=False,rope_ground_handoff=False):
        self.tracks=[];self.next_id=1;self.mode=None;self.reference_y=None
        self.camera_y=0.;self.camera_vy=0.;self.scroll_vx=0.
        self.last_translation=-1e9
        self.scroll_samples=deque(maxlen=7)
        self.scroll_position=0.;self.instant_vx=0.
        self.translation_source=None
        self.line_camera_recovery=line_camera_recovery
        self.camera_motion_source=None
        self.texture_camera_recovery=texture_camera_recovery
        self.last_texture_camera=None
        self.last_observation_stamp=None
        self.rope_ground_handoff=rope_ground_handoff

    def associate(self,segments,stamp,texture=None,*,camera_prior=None):
        candidates=[]
        for i,s in enumerate(segments):
            for j,old in enumerate(self.tracks):
                dt=stamp-old['stamp']
                if old['kind']!=s['kind']or not 0<dt<.25:continue
                a=np.asarray(s['a']);b=np.asarray(s['b'])
                oa=np.asarray(old['a'])+np.array([old['vx'],old['vy']])*dt
                ob=np.asarray(old['b'])+np.array([old['vx'],old['vy']])*dt
                cost=float(np.linalg.norm((a+b-oa-ob)/2))
                if cost<max(45,1200*dt)and abs((b-a)[1]-(ob-oa)[1])<40:
                    candidates.append((cost,i,j))
        paired={};used=set()
        for _,i,j in sorted(candidates):
            if i not in paired and j not in used:paired[i]=j;used.add(j)
        current=[];translations=[];references=[]
        for i,segment in enumerate(segments):
            s=dict(segment,stamp=stamp,observations=1,vx=0.,vy=0.,
                   left_clipped=bool(segment.get('left_clipped')or segment['a'][0]<=12),
                   right_clipped=bool(segment.get('right_clipped')or segment['b'][0]>=628))
            if i in paired:
                old=self.tracks[paired[i]];dt=stamp-old['stamp'];s['id']=old['id'];history=old['history']
                s['observations']=old.get('observations',1)+1
                # Cropped endpoints move when the other end leaves the image.
                # Estimate translation only from endpoints clear of the crop.
                shifts=[]
                for key in('a','b'):
                    a,b=np.asarray(s[key]),np.asarray(old[key])
                    clipped='left_clipped'if key=='a'else'right_clipped'
                    # OBB truncation can retract a full-screen endpoint tens
                    # of pixels inside the crop. Keep a wider uncertainty band
                    # for measuring velocity than for rendering finite edges.
                    if not s[clipped]and not old[clipped]and 32<a[0]<608 and 32<b[0]<608:shifts.append((a-b)/dt)
                if shifts:
                    history.append(np.median(shifts,axis=0))
                    if s['kind']!='floating_platform'and min(s['confidence'],old['confidence'])>=.7:
                        translations.extend(shifts)
                if history:s['vx'],s['vy']=map(float,np.median(np.asarray(history),axis=0))
                else:s['vx'],s['vy']=old['vx'],old['vy']
            else:
                s['id']=self.next_id;self.next_id+=1;history=deque(maxlen=6)
            s['history']=history;current.append(s)
            if i in paired and s['kind']!='floating_platform'and min(s['confidence'],self.tracks[paired[i]]['confidence'])>=.7:
                references.append((s,self.tracks[paired[i]]))
        if translations or texture is not None:
            self.instant_vx=float(np.median(translations,axis=0)[0])if translations else texture['vx']
            self.translation_source='support_endpoint'if translations else'ground_texture'
            previous_stamp=self.tracks[0]['stamp']
            if previous_stamp-self.last_translation>.15:
                self.scroll_samples.clear();self.scroll_position=0.
            if not self.scroll_samples:self.scroll_samples.append((previous_stamp,self.scroll_position))
            self.scroll_position+=self.instant_vx*(stamp-previous_stamp)
            self.scroll_samples.append((stamp,self.scroll_position))
            self.scroll_vx=self.instant_vx
            # Capture requests sample a 60Hz presented image at another rate.
            # One-frame differences alternate between one and two render steps;
            # fit displacement over several exposures instead of declaring that
            # a constant-speed platform repeatedly halves/doubles its speed.
            if len(self.scroll_samples)>=4:
                samples=np.asarray(self.scroll_samples);times=samples[:,0]-stamp
                if -times[0]>=.06:
                    centered=times-times.mean()
                    self.scroll_vx=float(centered@(samples[:,1]-samples[:,1].mean())/(centered@centered))
            self.last_translation=stamp
        # Endpoint Y translation measures the camera; the height at the runner
        # also changes as a slope scrolls past. Subtracting that local height
        # from enemy tracks would count the runner's climb/descent twice.
        shifts=[];velocities=[]
        for s,old in references:
            dt=stamp-old['stamp'];px=(max(s['a'][0],old['a'][0])+min(s['b'][0],old['b'][0]))/2
            def line_y(segment,x):
                a,b=segment['a'],segment['b']
                return a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0])
            slope=(old['b'][1]-old['a'][1])/(old['b'][0]-old['a'][0])
            # Camera displacement is an exposure-to-exposure quantity. Use
            # that interval's translation here, not the smoothed forecast speed.
            shift=line_y(s,px)-line_y(old,px)+slope*self.instant_vx*dt
            shifts.append(shift);velocities.append(shift/dt)
            if not s['history']:s['vx']=self.scroll_vx
        self.camera_motion_source='support_track'if shifts else None
        if not shifts and self.line_camera_recovery and self.tracks:
            dt=stamp-self.tracks[0]['stamp']
            dx=self.instant_vx*dt if translations or texture is not None else None
            recovered=overlapping_static_camera_shift(current,self.tracks,dx)
            if recovered is not None:
                shifts.append(recovered);velocities.append(recovered/dt)
                self.camera_motion_source='support_line_overlap'
        if self.texture_camera_recovery and self.tracks:
            dt=stamp-self.tracks[0]['stamp']
            dy=texture.get('camera_dy')if texture else None
            # A measured displacement belongs to this exact image interval.
            # A stale/invalid texture result cannot become camera evidence.
            measured=(dy is not None and np.isfinite(dy)and .006<=dt<=.16
                      and abs(texture.get('dt',0)-dt)<1e-6)
            if measured:
                shifts=[dy];velocities=[dy/dt]
                self.last_texture_camera=(stamp,dy/dt)
                self.camera_motion_source='ground_patch'
            elif (not shifts and self.last_texture_camera is not None
                  and .006<=dt<=.16 and 0<stamp-self.last_texture_camera[0]<.12
                  and any(s['kind']=='platform'for s in current)):
                # Brief measurement gaps use only the recent pixel velocity.
                # Mark the extrapolation explicitly and expire it after 120ms.
                velocity=self.last_texture_camera[1]
                shifts=[velocity*dt];velocities=[velocity]
                self.camera_motion_source='ground_patch_prediction'
        if not shifts and camera_prior is not None and self.last_observation_stamp is not None:
            dt=stamp-self.last_observation_stamp;dy=camera_prior.get('dy')
            if (dy is not None and np.isfinite(dy)and abs(dy)<=35 and .006<=dt<=.16
                    and abs(camera_prior.get('dt',0)-dt)<1e-6):
                shifts=[dy];velocities=[dy/dt]
                self.camera_motion_source='own_jump_prior'
        self.camera_vy=float(np.median(velocities))if velocities else 0.
        if shifts:self.camera_y+=float(np.median(shifts))
        self.tracks=current
        self.last_observation_stamp=stamp
        return [{k:v for k,v in s.items()if k!='history'}for s in current]

    def observe(self,segments,player,stamp,texture=None,*,camera_prior=None):
        segments=self.associate(segments,stamp,texture,camera_prior=camera_prior)
        px,py=player.center if player else(180.,None)
        choices=[]
        for s in segments:
            y=height(s,px)
            if y is None or py is None:continue
            distance=abs(abs(y-py)-30)if s['kind']=='rope'else abs(y-py-30)
            if distance<18:choices.append((distance,s,y))
        foot_support=None
        if choices:
            _,selected,y=min(choices,key=lambda c:c[0])
            self.mode='rope'if selected['kind']=='rope'else'ground';self.reference_y=y
            if self.mode=='ground':foot_support=selected
        # Keep mode through a jump, while current detected lines supply camera
        # height. A missing line is never fabricated as solid ground.
        ropes=[s for s in segments if s['kind']=='rope'and s['a'][0]-10<=px<=s['b'][0]+10]
        rope=None
        if self.mode=='rope'and ropes:
            selected=min(ropes,key=lambda s:abs((s['a'][1]+s['b'][1])/2-(self.reference_y or 260)))
            rope=height(selected,min(max(px,selected['a'][0]),selected['b'][0]));self.reference_y=rope
        terrain=None
        ground=[s for s in segments if s['kind']!='rope']
        if self.rope_ground_handoff and self.mode=='rope'and rope is None and player is not None:
            ropes=[s for s in segments if s['kind']=='rope']
            finished=[s for s in ropes if s['confidence']>=.7 and not s['right_clipped']and s['b'][0]<px-10]
            # Require a visible ground entrance joined to a genuine finite
            # rope end, already behind the role. A lost/cropped rope or a
            # floating surface underneath it cannot change the context.
            if finished and not any(s['b'][0]>=px-10 for s in ropes):
                joined=[]
                for g in ground:
                    if (g['kind']!='platform'or not g['a'][0]<=px<=g['b'][0]
                            or g['confidence']<.5 and g['observations']<3):continue
                    for r in finished:
                        if abs(g['a'][0]-r['b'][0])>24:continue
                        x=min(max(r['b'][0],g['a'][0]),g['b'][0])
                        if np.linalg.norm(np.asarray(r['b'])-np.array([x,height(g,x)]))<=16:
                            joined.append(g);break
                if joined:
                    selected=min(joined,key=lambda s:abs(height(s,px)-py))
                    self.mode='ground';self.reference_y=height(selected,px)
        if self.mode!='rope'and ground:
            expected=self.reference_y if self.reference_y is not None else(py+30 if py is not None else 260)
            selected=foot_support or min(ground,key=lambda s:(
                abs((height(s,min(max(px,s['a'][0]),s['b'][0]))or 0)-expected),
                max(0,s['a'][0]-px,px-s['b'][0])))
            y=height(selected,min(max(px,selected['a'][0]),selected['b'][0]));self.reference_y=y
            terrain=describe_terrain(ground,selected,px)
        # Forecast in the current camera plane. Floating surfaces retain their
        # own vertical motion after the common camera translation is removed.
        static=[s['vy']for s in segments if s['kind']!='floating_platform']
        camera_velocity=float(np.median(static))if static else self.camera_vy
        if self.camera_motion_source in('ground_patch','ground_patch_prediction','own_jump_prior'):
            camera_velocity=self.camera_vy
        forecast=[dict(s,vy=s['vy']-camera_velocity if s['kind']=='floating_platform'else 0.,
                       vx=s['vx']if s['kind']=='floating_platform'else self.scroll_vx)for s in segments]
        if terrain:
            terrain=dict(terrain,segments=[s for s in forecast if s['kind']!='rope'])
        rope_segment=next((s for s in forecast if rope is not None and s['id']==selected['id']),None)
        return dict(mode=self.mode,rope=rope,rope_segment=rope_segment,rope_segments=[s for s in forecast if s['kind']=='rope'],terrain=terrain,segments=forecast,
                    tracking_reference=(0.,self.camera_y),camera_vy=self.camera_vy,
                    scene_vx=self.scroll_vx,scene_vx_raw=self.instant_vx,
                    scene_motion_source=self.translation_source,
                    scene_motion_observed=stamp-self.last_translation<.2)
