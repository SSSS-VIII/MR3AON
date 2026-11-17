"""Short-horizon avoidance over visual objects, support and native action priors."""
from arena_vision import Box,Track,player_future,native_motion_box,can_air_down,track_confidence,create_motion,root_foot_box,constrain_ground_motion
from arena_oriented import is_box,transform,touching_capsule
from arena_support import leading_ground_faces
import arena_motion as motion


def ground_slide_supported(observation):
    """The existing slide prior describes solid ground, not a float down-pass.

    Original non-avoiding ItemAirGround turns a grounded down key into fall,
    retaining the full collider and allowing jump2 next. Pixels identifying a
    floating platform do not prove its hidden avoid-fall flag, so that surface
    cannot certify the solid-ground slide trajectory.
    """
    terrain=observation.get('terrain')
    if not terrain:return False
    if terrain.get('source')!='neural_segments':return True
    selected=next((s for s in terrain.get('segments',[])
                   if s.get('id')==terrain.get('selected_id')),None)
    return bool(selected and selected.get('kind')=='platform'
                and selected.get('raw_kind')!='floating_platform')


def collision_weight(track):
    # Blocking the runner against a scrolling ground entrance is terminal;
    # ordinary uncertain enemy contacts retain the existing health-loss cost.
    return 10 if track.kind=='terrain_wall'else 1


def touching(player,hazard,margin=4,*,shape="ellipse"):
    """Capsule/expanded-ellipse approximation, never a replacement game collider."""
    x,y=player.center;hx,hy=hazard.center
    dx=max(0,abs(x-hx)-max(0,(player.w-player.h)/2))
    dy=max(0,abs(y-hy)-max(0,(player.h-player.w)/2))
    radius=min(player.w,player.h)/2
    if shape=='box':
        return max(0,dx-hazard.w/2)**2+max(0,dy-hazard.h/2)**2<(radius+margin)**2
    return (dx/(hazard.w/2+radius+margin))**2+(dy/(hazard.h/2+radius+margin))**2<1


class Avoider:
    solid_ground_slide_only=False

    def __init__(self,*,continuous_collision=False):
        self.continuous_collision=continuous_collision
        self.last_action=-10
        self.followup_until=-10
        self.safe_upper_since=None

    def _jump(self,obs,p,t):
        return native_motion_box(dict(obs,player=p),'jump2'if obs['jumps']>=1 else'jump1',t)

    def _path(self,obs,action,t):
        p=obs['player']
        if action=='none':
            return player_future(obs,t)
        if action=='jump':
            return self._jump(obs,p,t)
        if action=='air_down':
            return native_motion_box(obs,'air_down',t)
        if action in ('flip','escape'):
            below=obs['phase']=='rope_below'
            name='rope_up'if below else'rope_down'
            target=native_motion_box(obs,name,min(t,motion.duration(name)))
            if action=='escape'and t>motion.duration(name):
                return self._jump(dict(obs,jumps=0,motion=None),target,t-motion.duration(name))
            return target
        if action=='slide':
            return native_motion_box(obs,'slide',t)
        raise ValueError(action)

    def _objects(self,obs):
        p=obs['player']
        threshold=obs.get('hazard_confidence',.7)
        objects=[t for t in obs['tracks'] if t.kind!='slice_target'and track_confidence(t,obs['time'])>=threshold
                and (t.observations>=3 or t.arming or t.active)
                and t.box.x+t.box.w>p.x-100]
        for face in leading_ground_faces(obs.get('visible_supports',[]),obs['time']):
            if face['x']<p.x-100:continue
            objects.append(Track(-1000000-face['id'],Box(face['x'],face['y'],1,1000),
                'terrain_wall',face['confidence'],obs['time'],observations=3,
                vx=face['vx'],vy=face['vy'],resource='derived_ground_entrance',collider_shape='BoxCollider'))
        return objects

    def _targets(self,obs):
        return [t for t in obs['tracks']if t.kind=='slice_target'and t.confidence>=.8
                and t.observations>=3 and t.box.x+t.box.w>obs['player'].x]

    def _hazard(self,track,t):
        box=track.future(t)
        # A visible attack wind-up/dash supplies a speed prior before two fresh
        # positions exist. The measured velocity remains separately logged.
        if track.arming or track.active and track.vx>-250:
            box.x=track.box.x+min(track.vx,-850)*t
        return box

    def _risk(self,obs,action):
        if self.continuous_collision:
            from arena_reactive_sweep import reactive_risk
            return reactive_risk(self,obs,action)
        return self._endpoint_risk(obs,action)

    def _endpoint_risk(self,obs,action):
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

    def _path_state(self,obs,action,t,player):
        active=obs.get('motion')
        if action=='jump':active=create_motion(obs,'jump2'if obs['jumps']>=1 else'jump1')
        elif action=='air_down':active=create_motion(obs,'air_down')
        elif action in ('flip','escape'):
            name='rope_up'if obs['phase']=='rope_below'else'rope_down'
            active=create_motion(obs,name)
            if action=='escape'and t>motion.duration(name):
                active=dict(name='jump1',started=obs['time']+motion.duration(name))
        elif action=='slide':active=create_motion(obs,'slide')
        phase=motion.phase(active['name'],obs['time']+t-active['started'],active)if active else obs['phase']
        return dict(obs,player=player,time=obs['time']+t,motion=active,phase=phase)

    def choose(self,obs):
        p,stamp=obs['player'],obs['time']
        if p is None:
            return None,'unknown_player'
        landing_ready=bool(obs.get('ground_contact_observed')and stamp-self.last_action>=.1)
        ground=obs.get('terrain')
        if ground and ground['y']is not None:
            edge=ground['edge']
            if (edge is not None and obs['phase'] in ('ground','slide')
                    and -20<edge-root_foot_box(obs).center[0]<max(48,(ground['speed']or 0)*.14)
                    and(stamp-self.last_action>.3 or landing_ready)):
                self.last_action=stamp
                return 'jump','ground_edge'
            if (obs['jumps']==1 and 'falling' in obs['phase'] and not ground['at_player']
                    and p.center[1]>ground['y']-65
                    and (ground['landing']is None or ground['landing']>p.center[0]+70)
                    and stamp-self.last_action>.3):
                self.last_action=stamp
                return 'jump','extend_gap_jump'
        if (stamp<self.followup_until and stamp-self.last_action>.26 and obs['phase']=='rope_above'):
            self.followup_until=-10
            # Recheck the second input from the new image. A sequence which was
            # safe before the flip can meet a newly arrived spider afterwards.
            stay=self._risk(obs,'none')[0];jump=self._risk(obs,'jump')[0]
            if jump==0 and stay>0:
                self.last_action=stamp
                return 'jump','complete_under_rope_escape'
        early_down=can_air_down(obs)and stamp-self.last_action>=.1
        if stamp-self.last_action<.32 and not(early_down or landing_ready):
            return None,'action_transition'
        if obs['phase']=='rope_below' and obs.get('rope')is not None:
            upper=Box(p.x,2*obs['rope']-p.y-p.h,p.w,p.h)
            occupied=any(t.confidence>=.7 and p.x-50<t.box.x<p.x+400
                         and upper.y<t.box.y+t.box.h+12 and upper.y+upper.h+12>t.box.y
                         for t in obs['tracks'])
            if occupied:
                self.safe_upper_since=None
            elif self.safe_upper_since is None:
                self.safe_upper_since=stamp
            elif stamp-self.safe_upper_since>.75:
                self.safe_upper_since=None;self.last_action=stamp
                return 'jump','neutral_above'
        else:
            self.safe_upper_since=None
        none,eta,hits=self._risk(obs,'none')
        if not hits or eta>.44:
            return None,'clear' if not hits else 'approaching'
        first=min(hits.values(),key=lambda v:v[0])[1]
        if first.sine_count==1 and eta>.18:
            return None,'confirm_curved_motion'
        candidates=[]
        if obs['phase'].startswith('rope_') and obs.get('rope')is not None:
            candidates.append(('flip',.03))
            if obs['phase']=='rope_below':
                candidates.append(('escape',.08))
        if obs['jumps']<2 and obs['phase']!='rope_below'and not obs['phase'].startswith('flip'):
            # A wind-up can be evaded early by changing sides. A jump is timed
            # after movement begins so its apex coincides with the crossing.
            if first.active or not first.arming:
                candidates.append(('jump',.05))
        if can_air_down(obs):candidates.append(('air_down',.03))
        if stamp-self.last_action<.32 and not landing_ready:
            candidates=[c for c in candidates if c[0]=='air_down']
        if (obs['phase']=='ground' and ground and
                (not self.solid_ground_slide_only or ground_slide_supported(obs))):
            candidates.append(('slide',.02))
        scored=[(self._risk(obs,a)[0]+effort,a)for a,effort in candidates]
        if not scored:
            return None,'waiting_for_dash'
        cost,action=min(scored)
        if cost>10 and eta>.16:
            return None,'wait_for_better_window'
        if cost>=none and eta>.16:
            return None,'wait_for_better_window'
        self.last_action=stamp
        if action=='flip':
            return ('jump' if obs['phase']=='rope_below' else 'down'),f'flip:{first.id}'
        if action=='escape':
            self.followup_until=stamp+.9
            return 'jump',f'under_rope_escape:{first.id}'
        if action=='air_down':return 'down',f'air_down:{first.id}'
        return action,f'{action}:{first.id}'


class VisualAvoider(Avoider):
    """Class motion priors for collider-trained visual detections.

    Basic spiders enter with a fast drop/rebound and then stay at their anchor;
    extrapolating that entry velocity for a whole crossing invents a new path.
    Native paired episodes favor the stopped vertical model over constant
    velocity at 300 ms. Keep the measured velocity in telemetry unchanged.
    Flying enemies retain the measured trajectory and wind-up/dash prior.
    """
    def _hazard(self,track,t):
        if track.attack_phase in ('ready','rush'):
            return track.future(t)
        box=super()._hazard(track,t)
        if track.kind=='spider' and track.sine_count<2:
            box.y=track.box.y
        return box
