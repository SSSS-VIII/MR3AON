from arena_policy import *
from arena_vision import constrain_ground_motion,root_foot_box

class VisualAvoider(VisualAvoider):
    def _risk(self,obs,action):
        objects=self._objects(obs)
        obs=dict(obs,blocking_faces=[dict(x=t.box.x,y=t.box.y,vx=t.vx,vy=t.vy,stamp=obs['time'])
                                    for t in objects if t.kind=='terrain_wall'])
        hits={};wall_frames={}
        previous=obs;lost_x=0.
        for step in range(1,20):
            t=step*.04
            p=self._path(obs,action,t)
            base_x=p.x;p=Box(p.x+lost_x,p.y,p.w,p.h)
            state=self._path_state(obs,action,t,p)
            state=constrain_ground_motion(previous,state);p=state['player'];lost_x=p.x-base_x;previous=state
            foot=None
            for track in objects:
                if track.id in hits and track.kind!='terrain_wall':continue
                hazard=self._hazard(track,t)
                if track.kind=='terrain_wall':
                    if foot is None:foot=root_foot_box(state)
                    collision=(abs(foot.center[0]-hazard.center[0])<hazard.w/2+
                               motion.DATA['blocking']['climb_distance']*obs.get('scale_px',41.)+4
                               and hazard.y-2<foot.center[1]<hazard.y+hazard.h+2)
                    if collision:wall_frames[track.id]=wall_frames.get(track.id,0)+1
                elif getattr(track,'quad',None)is not None and track.collider_shape=='BoxCollider':
                    quad=transform(track.quad,track.angular_velocity*t,hazard.center)
                    collision=touching_capsule(p,quad,margin=4)
                else:
                    collision=touching(p,hazard,shape='box'if is_box(track)else'ellipse')
                if collision:
                    hits.setdefault(track.id,(t,track))
        cost=sum(100*collision_weight(track)*(1+(.8-t)*2) for t,track in hits.values()if track.kind!='terrain_wall')
        cost+=sum(100*10*n*.04 for n in wall_frames.values())
        return cost,min((t for t,_ in hits.values()),default=10),hits
