"""Visible line association and support state; no native state or color rules."""
from collections import deque
import numpy as np


def leading_ground_faces(segments,stamp):
    """Visible solid-ground entrances; floating surfaces and joined seams aren't walls.

    These faces are derived geometry, never extra detector/native enemy labels.
    A six-pixel top tolerance avoids penalising normal surface contact.
    """
    ground=[s for s in segments if s['kind']=='platform'and s.get('confidence',0)>=.7]
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
    a=np.asarray(segment['a'],float)+np.array([segment.get('vx',0),segment.get('vy',0)])*seconds
    b=np.asarray(segment['b'],float)+np.array([segment.get('vx',0),segment.get('vy',0)])*seconds
    if not a[0]<=x<=b[0]or b[0]-a[0]<4:return None
    return float(a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0]))


def landing_height(terrain,x,seconds,from_y):
    """Future visible surface below the current capsule center, if any."""
    values=[y for s in terrain.get('segments',[])if s['kind']!='rope'
            for y in[height(s,x,seconds)]if y is not None and y>=from_y-2]
    return min(values)if values else None


def describe_terrain(ground,selected,px):
    y=height(selected,min(max(px,selected['a'][0]),selected['b'][0]))
    samples=[]
    for x in range(0,640,4):
        ys=[v for s in ground for v in[height(s,x)]if v is not None]
        value=min(ys,key=lambda v:abs(v-y))if ys else y
        samples.append((x,value-7,bool(ys)))
    edge=selected['b'][0]if selected['b'][0]<637 else None
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
    return describe_terrain(segments,selected,px)


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


class VisualSupports:
    def __init__(self):
        self.tracks=[];self.next_id=1;self.mode=None;self.reference_y=None
        self.camera_y=0.;self.camera_vy=0.;self.scroll_vx=0.

    def associate(self,segments,stamp):
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
            s=dict(segment,stamp=stamp,vx=0.,vy=0.)
            if i in paired:
                old=self.tracks[paired[i]];dt=stamp-old['stamp'];s['id']=old['id'];history=old['history']
                # Cropped endpoints move when the other end leaves the image.
                # Estimate translation only from endpoints clear of the crop.
                shifts=[]
                for key in('a','b'):
                    a,b=np.asarray(s[key]),np.asarray(old[key])
                    if 3<a[0]<637 and 3<b[0]<637:shifts.append((a-b)/dt)
                if shifts:
                    history.append(np.median(shifts,axis=0))
                    if s['kind']!='floating_platform'and min(s['confidence'],old['confidence'])>=.7:
                        translations.append(np.median(shifts,axis=0))
                if history:s['vx'],s['vy']=map(float,np.median(np.asarray(history),axis=0))
                else:s['vx'],s['vy']=old['vx'],old['vy']
            else:
                s['id']=self.next_id;self.next_id+=1;history=deque(maxlen=6)
            s['history']=history;current.append(s)
            if i in paired and s['kind']!='floating_platform'and min(s['confidence'],self.tracks[paired[i]]['confidence'])>=.7:
                references.append((s,self.tracks[paired[i]]))
        if translations:self.scroll_vx=float(np.median(translations,axis=0)[0])
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
            shift=line_y(s,px)-line_y(old,px)+slope*self.scroll_vx*dt
            shifts.append(shift);velocities.append(shift/dt)
            if not s['history']:s['vx']=self.scroll_vx
        self.camera_vy=float(np.median(velocities))if velocities else 0.
        if shifts:self.camera_y+=float(np.median(shifts))
        self.tracks=current
        return [{k:v for k,v in s.items()if k!='history'}for s in current]

    def observe(self,segments,player,stamp):
        segments=self.associate(segments,stamp)
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
        forecast=[dict(s,vy=s['vy']-camera_velocity if s['kind']=='floating_platform'else 0.)for s in segments]
        if terrain:
            terrain=dict(terrain,segments=[s for s in forecast if s['kind']!='rope'])
        rope_segment=next((s for s in forecast if rope is not None and s['id']==selected['id']),None)
        return dict(mode=self.mode,rope=rope,rope_segment=rope_segment,terrain=terrain,segments=forecast,
                    tracking_reference=(0.,self.camera_y),camera_vy=self.camera_vy)
