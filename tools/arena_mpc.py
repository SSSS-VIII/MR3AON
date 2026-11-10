"""Receding-horizon search over original actions and visual hazard trajectories."""
from dataclasses import dataclass
import numpy as np
from arena_vision import advance_player,native_motion_box,create_motion,can_air_down,root_foot_box
from arena_policy import VisualAvoider,collision_weight
import arena_motion as motion
from arena_object_motion import PRIORS
from arena_oriented import is_box,swept_capsules


@dataclass
class Node:
    state: dict
    cost: float=0.
    first: str|None=None
    hits: frozenset=frozenset()
    actions: int=0
    target_hits: frozenset=frozenset()


def advance(state,seconds):
    return advance_player(state,seconds)


def start_action(state,name):
    active=create_motion(state,name)
    return dict(state,player=native_motion_box(state,name,0),
                motion=active,phase=motion.phase(name,0,active),
                jumps=1 if name=='jump1'else 2 if name=='jump2'else 0)


def player_array(states):
    return np.array([[*s['player'].center,s['player'].w,s['player'].h]for s in states])


def foot_array(states):
    return np.array([[*root_foot_box(s).center,0.,0.]for s in states])


def forecast_geometry(tracks,times,predict,step):
    boxes=np.array([[[b.center[0],b.center[1],b.w/2,b.h/2]
                     for track in tracks for b in[predict(track,t)]]for t in times]).reshape(len(times),len(tracks),4)
    for index,track in enumerate(tracks):
        if hasattr(track,'sweep_margin'):boxes[:,index,2:]+=track.sweep_margin(step)
    box_shapes=np.array([is_box(t)for t in tracks],bool)
    oriented=np.array([getattr(t,'quad',None)is not None and t.collider_shape=='BoxCollider'for t in tracks],bool)
    if not np.any(oriented):return boxes,box_shapes,oriented,None,None
    indices=np.flatnonzero(oriented)
    base=np.array([tracks[j].quad for j in indices]);offsets=base-base.mean(axis=1,keepdims=True)
    angles=times[:,None]*np.array([tracks[j].angular_velocity for j in indices])[None,:]
    cos=np.cos(angles)[:,:,None];sin=np.sin(angles)[:,:,None]
    quads=np.stack((offsets[None,:,:,0]*cos-offsets[None,:,:,1]*sin,
                    offsets[None,:,:,0]*sin+offsets[None,:,:,1]*cos),axis=-1)
    quads+=boxes[:,indices,None,:2]
    radius=np.linalg.norm(quads[0]-quads[0].mean(axis=1,keepdims=True),axis=2).max(axis=1)
    step_angle=np.array([abs(tracks[j].angular_velocity)*step for j in indices])
    sagitta=radius*(1-np.cos(np.minimum(np.pi,step_angle)/2))
    return boxes,box_shapes,oriented,quads,sagitta


def swept_distances(before,after,old,new,margin,box_hazards=None,box_vertical_margin=None):
    """All candidate capsules against all hazards in one broadcast operation.

    Player rows are centerX/centerY/width/height, hazard rows centerX/centerY/
    halfWidth/halfHeight. Preserve the same conservative swept geometry per pair.
    """
    radius=np.maximum(np.minimum(before[:,2],before[:,3]),np.minimum(after[:,2],after[:,3]))/2
    rx=np.maximum(old[:,2],new[:,2])[None,:]+radius[:,None]+margin
    ry=np.maximum(old[:,3],new[:,3])[None,:]+radius[:,None]+margin
    radii=np.stack((rx,ry),axis=2)
    a=(old[None,:,:2]-before[:,None,:2])/radii
    b=(new[None,:,:2]-after[:,None,:2])/radii
    core=np.maximum(0,np.maximum((before[:,3]-before[:,2])/2,(after[:,3]-after[:,2])/2))
    spine=core[:,None]/ry
    def endpoint(p):return p[:,:,0]**2+np.maximum(0,abs(p[:,:,1])-spine)**2
    distance=np.minimum(endpoint(a),endpoint(b));v=b-a;norm=np.sum(v*v,axis=2)
    for sign in(-1,1):
        end=np.stack((np.zeros_like(spine),sign*spine),axis=2)
        fraction=np.clip(np.sum((end-a)*v,axis=2)/np.maximum(norm,1e-12),0,1)
        distance=np.minimum(distance,np.sum((a+fraction[:,:,None]*v-end)**2,axis=2))
    fraction=-a[:,:,0]/np.where(abs(v[:,:,0])>1e-9,v[:,:,0],1e-9)
    intersects=(fraction>=0)&(fraction<=1)&(abs(a[:,:,1]+fraction*v[:,:,1])<=spine)
    distance[intersects]=0
    if box_hazards is not None and np.any(box_hazards):
        # Unknown trap orientation uses its observed AABB conservatively.
        # An ellipse inscribed in that box would miss its dangerous corners.
        relative=old[None,:,:2]-before[:,None,:2]
        velocity=(new[None,:,:2]-after[:,None,:2])-relative
        extent=np.maximum(old[:,2:],new[:,2:])[None,:,:]+radius[:,None,None]+margin
        extent=np.broadcast_to(extent,relative.shape).copy();extent[:,:,1]+=core[:,None]
        if box_vertical_margin is not None:
            extent[:,:,1]+=box_vertical_margin-margin
        parallel=abs(velocity)<1e-9;safe=np.where(parallel,1.,velocity)
        lo=(-extent-relative)/safe;hi=(extent-relative)/safe
        enter=np.minimum(lo,hi);leave=np.maximum(lo,hi)
        outside=abs(relative)>extent
        enter=np.where(parallel,np.where(outside,np.inf,-np.inf),enter)
        leave=np.where(parallel,np.where(outside,-np.inf,np.inf),leave)
        crossing=np.maximum(0,enter.max(axis=2))<=np.minimum(1,leave.min(axis=2))
        rectangular=np.where(crossing,0,np.maximum(1.,distance))
        distance=np.where(np.asarray(box_hazards)[None,:],rectangular,distance)
    return distance


def swept_distance(before,after,old,new,margin):
    """Single-candidate interface for geometry checks and diagnostics."""
    a=np.array([[*before.center,before.w,before.h]])
    b=np.array([[*after.center,after.w,after.h]])
    return swept_distances(a,b,old,new,margin)[0]


def crosses_rope_end_below(before,after):
    segment=before.get('rope_segment')
    if (segment is None or before.get('rope')is None or after.get('rope')is not None
            or segment.get('right_clipped',False)):
        return False
    next_segment=after['rope_segment'];a,b=segment['a'],segment['b']
    px,py=before['player'].center;nx,ny=after['player'].center
    r0=px-b[0];r1=nx-next_segment['b'][0]
    if not r0<=0<r1:return False
    fraction=-r0/(r1-r0)
    line_y=b[1]+fraction*(next_segment['b'][1]-b[1])
    return py+fraction*(ny-py)>line_y+5


class MpcAvoider(VisualAvoider):
    """Beam search, replanned from each frame; only its first input is executed."""
    STEP=.08
    STEPS=12
    BEAM=24

    def rope_exit(self,obs):
        segment=obs.get('rope_segment')
        if segment is None:return False
        relative=segment['vx']-obs.get('vx',0.)
        return (relative<0 and not segment.get('right_clipped',segment['b'][0]>=637)
                and 0<=segment['b'][0]-obs['player'].center[0]<=-relative*self.STEP*self.STEPS)

    def uses_search(self,obs):
        airborne_ground=bool(obs.get('terrain')and obs['terrain'].get('source')=='neural_segments'
                             and obs.get('phase','').startswith(('jump','air_')))
        return bool(obs.get('player')and (obs.get('rope')is not None and not obs.get('terrain')or airborne_ground)
                    and (self.rope_exit(obs)or self._targets(obs)or any(t.kind in ('pinball','trap','arrow','mace','terrain_wall')or t.attack_phase is not None for t in self._objects(obs))))

    def _options(self,state,stamp):
        names=[None]
        phase=state['phase']
        if phase=='rope_above':names+=['rope_down','jump1']
        elif phase=='ground'or phase.startswith('air_')and not state['jumps']:names+=['jump1']
        elif phase=='rope_below':names+=['rope_up']
        elif state['jumps']==1 and phase.startswith('jump1'):
            active=state.get('motion')
            if active and stamp-active['started']>=.17:names+=['jump2']
        if can_air_down(state):names+=['air_down']
        return names

    def choose(self,obs):
        if obs['player']is None:return None,'unknown_player'
        if not self.uses_search(obs):
            return super().choose(obs)
        tracks=self._objects(obs);targets=self._targets(obs)
        obs=dict(obs,blocking_faces=[dict(x=t.box.x,y=t.box.y,vx=t.vx,vy=t.vy,stamp=obs['time'])
                                    for t in tracks if t.kind=='terrain_wall'])
        if not tracks and not targets and not self.rope_exit(obs):return super().choose(obs)
        # The reactive native-action controller is cheaper and currently better
        # on unmodelled entry/dash hazards. Search uses bouncing crossings and
        # learned native attack phases, never stage or elapsed board time.
        if not self.uses_search(obs):
            return super().choose(obs)
        # Precompute all object forecasts once, outside the search branches.
        times=np.arange(self.STEPS*2+1)*self.STEP/2
        boxes,box_hazards,oriented,quads,sagitta=forecast_geometry(tracks,times,self._hazard,self.STEP/2)
        target_boxes,target_shapes,target_oriented,target_quads,target_sagitta=forecast_geometry(targets,times,self._hazard,self.STEP/2)
        has_oriented=bool(np.any(oriented))
        walls=np.array([t.kind=='terrain_wall'for t in tracks],bool)
        beam=[Node(obs)];now=obs['time']
        for step in range(self.STEPS):
            branches=[]
            for node in beam:
                options=self._options(node.state,node.state['time'])
                if step==0 and now-self.last_action<.17:
                    options=[name for name in options if name is None or name=='air_down'and now-self.last_action>=.1]
                for name in options:
                    state=start_action(node.state,name)if name else node.state
                    half=advance(state,self.STEP/2);end=advance(state,self.STEP)
                    branches.append((node,state,half,end,name))
            positions=[player_array([b[index]for b in branches])for index in(1,2,3)]
            feet=[foot_array([b[index]for b in branches])for index in(1,2,3)]if np.any(walls)else None
            distances=[];near=[];target_contacts=[]
            for sample in(0,1):
                index=step*2+sample
                d=swept_distances(positions[sample],positions[sample+1],
                                  boxes[index],boxes[index+1],8+times[index+1]*8,
                                  box_hazards=box_hazards,
                                  box_vertical_margin=PRIORS['trap_prediction']['vertical_margin_px']+
                                    times[index+1]*PRIORS['trap_prediction']['vertical_growth_px_per_second'])
                if has_oriented:
                    collision=swept_capsules(positions[sample],positions[sample+1],quads[index],quads[index+1],
                        margin_x=8+times[index+1]*8,
                        margin_y=PRIORS['trap_prediction']['vertical_margin_px']+
                                 times[index+1]*PRIORS['trap_prediction']['vertical_growth_px_per_second'],sagitta=sagitta)
                    d[:,oriented]=np.where(collision,0,np.maximum(1.,d[:,oriented]))
                if feet is not None:
                    d[:,walls]=swept_distances(feet[sample],feet[sample+1],boxes[index,walls],boxes[index+1,walls],
                        motion.DATA['blocking']['climb_distance']*obs.get('scale_px',41.)+8,
                        box_hazards=np.ones(int(walls.sum()),bool),box_vertical_margin=2.)
                distances.append(d);near.append(np.maximum(0,1.4-d).sum(axis=1)*.002)
                if targets:
                    contact=swept_distances(positions[sample],positions[sample+1],
                        target_boxes[index],target_boxes[index+1],0,box_hazards=target_shapes)<1
                    if np.any(target_oriented):
                        contact[:,target_oriented]=swept_capsules(positions[sample],positions[sample+1],
                            target_quads[index],target_quads[index+1],sagitta=target_sagitta)
                    target_contacts.append(contact)
            pool={}
            for i,(node,state,half,end,name)in enumerate(branches):
                hits=set(node.hits);target_hits=set(node.target_hits);cost=node.cost
                for sample in(0,1):
                    for index in np.flatnonzero(distances[sample][i]<1):
                        identity=tracks[index].id
                        if walls[index]:
                            cost+=1000*collision_weight(tracks[index])*self.STEP/2;hits.add(identity)
                        elif identity not in hits:
                            cost+=1000*collision_weight(tracks[index])*(1-.2*(step+1)/self.STEPS);hits.add(identity)
                    cost+=float(near[sample][i])
                    if targets:target_hits.update(targets[j].id for j in np.flatnonzero(target_contacts[sample][i]))
                # Predicted contacts count once per target within this horizon.
                # The total bonus stays below even one ordinary collision cost.
                cost-=.1*(min(10,len(target_hits))-min(10,len(node.target_hits)))
                count=node.actions+bool(name)
                terrain=end.get('terrain')
                if (terrain and not terrain['at_player']and end['player'].center[1]>terrain['y']+35
                        and 'unsupported'not in hits):
                    cost+=10000;hits.add('unsupported')
                if ('below_rope_exit'not in hits and
                        (crosses_rope_end_below(state,half)or crosses_rope_end_below(half,end))):
                    cost+=10000;hits.add('below_rope_exit')
                if name:cost+=.05 if name.startswith('jump')else .03
                first=name if step==0 else node.first
                active=end.get('motion');age=0 if not active else round(end['time']-active['started'],3)
                key=(end['phase'],age,round(end['player'].center[1]/3),end['jumps'])
                candidate=Node(end,cost,first,frozenset(hits),count,frozenset(target_hits))
                if key not in pool or candidate.cost<pool[key].cost:
                    pool[key]=candidate
            beam=sorted(pool.values(),key=lambda n:(n.cost,n.actions))[:self.BEAM]
        best=min(beam,key=lambda n:(n.cost,n.actions))
        if not best.first:return None,'mpc_wait'
        self.last_action=now
        action='down'if best.first in ('rope_down','air_down')else'jump'
        return action,'mpc_'+best.first
