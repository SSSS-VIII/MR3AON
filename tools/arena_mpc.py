"""Receding-horizon search over original actions and visual hazard trajectories."""
from dataclasses import dataclass
import numpy as np
from arena_vision import advance_player,native_motion_box
from arena_policy import VisualAvoider
import arena_motion as motion


@dataclass
class Node:
    state: dict
    cost: float=0.
    first: str|None=None
    hits: frozenset=frozenset()
    actions: int=0


def advance(state,seconds):
    return advance_player(state,seconds)


def start_action(state,name):
    return dict(state,player=native_motion_box(state,name,0),
                motion=dict(name=name,started=state['time']),phase=motion.phase(name,0),
                jumps=1 if name=='jump1'else 2 if name=='jump2'else 0)


def player_array(states):
    return np.array([[*s['player'].center,s['player'].w,s['player'].h]for s in states])


def swept_distances(before,after,old,new,margin):
    """All candidate capsules against all hazards in one broadcast operation.

    Player rows are centerX/centerY/width/height, hazard rows centerX/centerY/
    radiusX/radiusY. Preserve the same conservative swept geometry per pair.
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
    return distance


def swept_distance(before,after,old,new,margin):
    """Single-candidate interface for geometry checks and diagnostics."""
    a=np.array([[*before.center,before.w,before.h]])
    b=np.array([[*after.center,after.w,after.h]])
    return swept_distances(a,b,old,new,margin)[0]


class MpcAvoider(VisualAvoider):
    """Beam search, replanned from each frame; only its first input is executed."""
    STEP=.08
    STEPS=12
    BEAM=24

    def uses_search(self,obs):
        return bool(obs.get('player')and obs.get('rope')is not None and not obs.get('terrain')
                    and any(t.kind=='pinball'or t.attack_phase is not None for t in self._objects(obs)))

    def _options(self,state,stamp):
        names=[None]
        phase=state['phase']
        if phase=='rope_above':names+=['rope_down','jump1']
        elif phase=='rope_below':names+=['rope_up']
        elif state['jumps']==1 and phase.startswith('jump1'):
            active=state.get('motion')
            if active and stamp-active['started']>=.17:names+=['jump2']
        return names

    def choose(self,obs):
        if obs['player']is None:return None,'unknown_player'
        if obs.get('rope')is None or obs.get('terrain'):
            return super().choose(obs)
        tracks=self._objects(obs)
        if not tracks:return super().choose(obs)
        # The reactive native-action controller is cheaper and currently better
        # on unmodelled entry/dash hazards. Search uses bouncing crossings and
        # learned native attack phases, never stage or elapsed board time.
        if not self.uses_search(obs):
            return super().choose(obs)
        # Precompute all object forecasts once, outside the search branches.
        times=np.arange(self.STEPS*2+1)*self.STEP/2
        boxes=np.array([[[b.center[0],b.center[1],b.w/2,b.h/2]
                         for track in tracks for b in[self._hazard(track,t)]]for t in times])
        beam=[Node(obs)];now=obs['time']
        for step in range(self.STEPS):
            branches=[]
            for node in beam:
                options=self._options(node.state,node.state['time'])
                if step==0 and now-self.last_action<.17:options=[None]
                for name in options:
                    state=start_action(node.state,name)if name else node.state
                    half=advance(state,self.STEP/2);end=advance(state,self.STEP)
                    branches.append((node,state,half,end,name))
            positions=[player_array([b[index]for b in branches])for index in(1,2,3)]
            distances=[];near=[]
            for sample in(0,1):
                index=step*2+sample
                d=swept_distances(positions[sample],positions[sample+1],
                                  boxes[index],boxes[index+1],8+times[index+1]*8)
                distances.append(d);near.append(np.maximum(0,1.4-d).sum(axis=1)*.002)
            pool={}
            for i,(node,state,half,end,name)in enumerate(branches):
                hits=set(node.hits);cost=node.cost
                for sample in(0,1):
                    for index in np.flatnonzero(distances[sample][i]<1):
                        identity=tracks[index].id
                        if identity not in hits:
                            cost+=1000*(1-.2*(step+1)/self.STEPS);hits.add(identity)
                    cost+=float(near[sample][i])
                count=node.actions+bool(name)
                if name:cost+=.05 if name.startswith('jump')else .03
                first=name if step==0 else node.first
                active=end.get('motion');age=0 if not active else round(end['time']-active['started'],3)
                key=(end['phase'],age,round(end['player'].center[1]/3),end['jumps'])
                candidate=Node(end,cost,first,frozenset(hits),count)
                if key not in pool or candidate.cost<pool[key].cost:
                    pool[key]=candidate
            beam=sorted(pool.values(),key=lambda n:(n.cost,n.actions))[:self.BEAM]
        best=min(beam,key=lambda n:(n.cost,n.actions))
        if not best.first:return None,'mpc_wait'
        self.last_action=now
        action='down'if best.first=='rope_down'else'jump'
        return action,'mpc_'+best.first
