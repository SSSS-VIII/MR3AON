"""Internal-state forecasts in original world coordinates, without image input.

This module never steps/restores a game. It reads per-instance native parameters,
keeps unsupported mechanics explicit, and compares trajectories before an action
is delivered. Forecasts are hypotheses checked against the original client by
arena_privileged_runner; they are not certificates of a route's safety.
"""
from dataclasses import dataclass, replace
from functools import lru_cache
import math
import numpy as np


REST = {'runonline', 'runonlinedown', 'runonground', 'slideonground'}
AIR = {'jump', 'fall', 'jump2', 'fall2', 'fallfromrun'}
TRANSFER = {'rolltolineon', 'rolltolinedown', 'rolltoground'}
POP = {'popup','popfall'}


def rows(value):
    # The client's encoder represents an empty Lua sequence as {}.
    if value == {} or value is None:
        return []
    if not isinstance(value, list):
        raise ValueError('Expected a native sequence')
    return value


def phase(value):
    return value.split(':')[0].lower()


def xy(value):
    return np.array([value['x'], value['y']], dtype=float)


@lru_cache(maxsize=2048)
def timer_ticks(value, step, strict_negative=True):
    """Original single-precision countdown, including its zero condition.

    .3f minus .02f fifteen times remains positive. A plain real-number .3
    second duration consequently fires one native tick early.
    """
    value, step = np.float32(value), np.float32(step)
    count = 0
    while value >= 0 if strict_negative else value > 0:
        value = np.float32(value-step); count += 1
        if count > 10000:
            raise ValueError('Unbounded native phase timer')
    return count


@dataclass(frozen=True)
class Surface:
    id: int | str
    left: float
    right: float
    y: float
    slope: float
    rope: bool
    vx: float = 0.
    vy: float = 0.
    platform: bool = False

    def height(self, x, t=0.):
        return self.y + self.vy*t + (x-self.left-self.vx*t)*self.slope

    def contains(self, x, t=0.):
        return self.left+self.vx*t-1e-5 <= x <= self.right+self.vx*t+1e-5


def surfaces(observation):
    result = []
    for row in rows(observation['supports']):
        a, b, info = row['start'], row['finish'], row['info']
        if b['x'] <= a['x'] or not (row['is_line'] or row['is_ground']):
            continue
        result.append(Surface(row['id'], a['x'], b['x'], a['y'],
                              (b['y']-a['y'])/(b['x']-a['x']), row['is_line']))
    for row in rows(observation.get('terrain')):
        a, b = row['start'], row['finish']
        if b['x'] <= a['x'] or phase(row['kind']) not in ('line', 'ground'):
            continue
        # Keep live identity where a collider already exists so the role's
        # native GroundCollider reference still selects the correct support.
        if any(abs(s.left-a['x']) < .001 and abs(s.right-b['x']) < .001 for s in result):
            continue
        result.append(Surface(row['id'], a['x'], b['x'], a['y'],
                              (b['y']-a['y'])/(b['x']-a['x']), phase(row['kind']) == 'line'))
    for row in rows(observation['platforms']):
        d = row['info']
        result.append(Surface(row['id'], d['_leftX'], d['_rightX'], d['_topY'], 0., False,
                              d.get('_speedX', 0.), d.get('_speedY', 0.),platform=True))
    return result


@dataclass
class Motor:
    x: float
    y: float
    vy: float
    mode: str
    used: int
    support: int | str | None
    elapsed: float = 0.
    delay: float = 0.
    lead_vy: float = 0.
    lead_gravity: float = 0.
    lead_mode: str = ''
    transfer_speed: float = 0.
    collider_delay: float = 0.
    vx: float = 0.
    offset_field: float = 0.
    offset_render: float = 0.
    slide_ticks: int = 0
    ground_source: bool = False
    physical_y: float = 0.
    previous_y: float = 0.
    physical_x: float = 0.
    previous_x: float = 0.
    native_air: bool = False
    native_transfer: bool = False
    spring_ready: bool = False
    spring_accel: float = 0.
    spring_event: float = -math.inf


class PlayerModel:
    def __init__(self, observation):
        self.observation = observation
        role, state = observation['role'], observation['state']
        self.data, self.parameters = role['data'], role['collider_parameters']
        self.rules = role.get('rules',{})
        self.surfaces = surfaces(observation)
        body = rows(role['colliders'])[0]
        self.scale = body['scale']
        self.body = body
        self.speed = state['speed']
        self.tick = state['fixedDeltaTime']
        self.clock_age = max(0., state['time']-role.get('fields',{}).get('_lastFixedUpdateTime',state['time']))
        self.shell_dash_speed=role.get('fields',{}).get('_shellDashSpeed',0.)
        self.foot = self.data['_ninjaFootPoint']
        mode = phase(state['physics'])
        used = 2 if mode in ('jump2', 'fall2') else 1 if mode in ('jump', 'fall') else 0
        self.initial = Motor(state['position']['x'], state['position']['y'],
                             role['velocity']['y'], mode, used, observation.get('support_id'))
        self.initial.vx=role['velocity']['x']
        self.initial.offset_field=role.get('fields',{}).get('_currRoleObjOffset',{}).get('x',0.)*self.scale['x']
        self.initial.offset_render=body['position']['x']-state['position']['x'] if 'position' in body else 0.
        if mode=='slideonground':
            self.initial.slide_ticks=timer_ticks(role['fields']['_slideRemainTime'],self.tick,False)
            self.initial.ground_source=True
        elif mode in ('runonground','runonline','runonlinedown'):
            self.initial.ground_source=True
        last=role.get('fields',{}).get('_lastPosition')
        previous=role.get('fields',{}).get('_secondLastPosition')
        self.native_samples=last is not None and previous is not None
        self.initial.native_air=self.native_samples and mode in AIR
        self.initial.native_transfer=self.native_samples and mode in TRANSFER
        if last is None:
            # Legacy captures omitted the native position history. Reconstruct
            # the constant-velocity anchors from the observed render pose;
            # current native captures retain their real samples unchanged.
            age=np.clip(self.clock_age,0.,self.tick)
            last={a:state['position'][a]+role['velocity'][a]*(self.tick-age)for a in ('x','y')}
        if previous is None:
            previous={a:last[a]-role['velocity'][a]*self.tick for a in ('x','y')}
        self.initial.physical_y,self.initial.previous_y=last['y'],previous['y']
        self.initial.physical_x,self.initial.previous_x=last['x'],previous['x']
        self.interaction_radius=0.
        for collider in rows(role.get('interaction_colliders')):
            if collider['type'] not in ('SphereCollider','CapsuleCollider'):
                continue
            scale=max(abs(collider['scale'][axis]) for axis in ('x','y','z'))
            radius=collider['radius']*scale
            if collider['type']=='CapsuleCollider':
                axis=('x','y','z')[collider['direction']]
                radial=max(abs(collider['scale'][a]) for a in ('x','y','z') if a!=axis)
                radius=max(collider['radius']*radial,
                           collider['height']*abs(collider['scale'][axis])/2)
            # Enclose both original pickup profiles at the role-object root;
            # the normal hurt capsule is much narrower than the pickup zone.
            offset=xy(collider['center'])-xy(state['position'])
            offset[0]-=self.initial.offset_render
            self.interaction_radius=max(self.interaction_radius,radius+np.linalg.norm(offset))
        self.contact_avoidance=[]
        current_platform = next((p for p in rows(observation['platforms']) if p['is_current']),None)
        if current_platform is not None:
            self.initial.support = current_platform['id']
        if mode in TRANSFER:
            self.initial.transfer_speed = (role['velocity']['y'] if mode=='rolltolineon'
                                           else abs(role['velocity']['y']))
        self.unsupported = []
        self.popfall_supported=False
        if mode=='popfall':
            f=role['fields'];direction=f.get('_popDirection',{})
            self.popfall_supported=(self.native_samples and f.get('_continuePop')is False and
                f.get('_popCanJump')is False and direction.get('x')==1 and direction.get('y')==0 and
                direction.get('z')==0 and self.initial.vx>0 and self.initial.vy<=0 and
                not rows(observation['platforms']) and '_downGravity3'in self.data and
                all(math.isfinite(v)for v in (self.initial.vx,self.initial.vy,self.data['_downGravity3'])) and
                role['velocity'].get('z',0)==0)
            if not self.popfall_supported:self.unsupported.append('native_popfall_variant')
        if mode not in REST | AIR | TRANSFER | POP:
            self.unsupported.append('role:'+mode)
        if role.get('mounted') or role.get('god'):
            self.unsupported.append('protected_or_mounted_role')
        if mode == 'slideonground' and 'slide_seconds' not in self.rules:
            self.unsupported.append('native_slide_parameters_missing')
        if role.get('air_ground') and role['air_ground'].get('_transparent'):
            self.unsupported.append('transparent_current_platform')
        for row in rows(observation['platforms']):
            if row['info'].get('_speedX') or row['info'].get('_speedY'):
                self.unsupported.append('moving_platform_activation')
        for row in rows(observation.get('terrain')):
            if (phase(row['kind']) not in ('line','ground') and
                    self.initial.x <= row['start']['x'] <= self.initial.x+self.speed*1.8):
                vertical_link=(phase(row['kind'])=='link' and
                               abs(row['finish']['x']-row['start']['x'])<.0001)
                if not vertical_link or '_climbDistance' not in self.data:
                    self.unsupported.append('terrain:'+row['kind'])
        if observation.get('camera',{}).get('direction',1) != 1:
            self.unsupported.append('reverse_running_direction')
        launch_speeds=[i['custom'].get('_popSpeed',0.)for i in rows(observation.get('mechanism_items'))
                       if i['type']=='ItemSpring']+[i['custom'].get('_popSpeed',0.)for i in rows(observation.get('pending_items'))
                       if i['info']['_itemType']=='ItemSpring: 15']
        reach_speed=max(self.speed,abs(self.initial.vx),*(v for v in launch_speeds if math.isfinite(v)))
        for item in rows(observation.get('mechanism_items')):
            dx=item['position']['x']-self.initial.x
            from arena_privileged_families import progression_marker
            if progression_marker(item):
                continue
            from arena_privileged_families import static_pickup,passive_fixed_item,coin_only_magnet,static_skull
            template=observation.get('spawn_templates',{}).get('items',{}).get(item['type'],{})
            if item['type']=='ItemFixed'and passive_fixed_item(item,template,observation,live=True):continue
            if item['type']=='ItemSkull':
                bound,_=static_skull(item,template,observation,live=True)
                if bound is not None:
                    self.contact_avoidance.append(bound);continue
            if item['type']in ('ItemMagnet','ItemElementBall'):
                bound,_=static_pickup(item,template,observation,live=True)
                if bound is not None:
                    if not(item['type']=='ItemMagnet'and coin_only_magnet(item,template)):
                        self.contact_avoidance.append(bound)
                    continue
            native_static_spring=(item['type']=='ItemSpring' and
                item['fields'].get('_needRotate') is False and
                item['fields'].get('isTrigger') is False and
                not item['fields'].get('beAttracting') and self.interaction_radius>0 and
                any(c.get('trigger') for c in rows(item.get('colliders'))) and
                all(c['type'] in ('BoxCollider','SphereCollider') for c in rows(item.get('colliders'))))
            if native_static_spring:
                self.contact_avoidance.append(item)
                continue
            if -self.interaction_radius-2<dx<reach_speed*1.8+self.interaction_radius+4:
                self.unsupported.append('item:'+item['type'])

        self.spring_launches=[]
        self.pickup_profile=None
        from arena_privileged_families import configure_springs,pending_item_issues,skill_issues,collect_effect_issues
        configure_springs(self)
        from arena_privileged_families import configure_pending_pickups
        configure_pending_pickups(self)
        self.unsupported.extend(pending_item_issues(self))
        self.unsupported.extend(skill_issues(role))
        self.unsupported.extend(collect_effect_issues(role))
        self.initial.spring_ready=self.popfall_supported

    def spring_distance(self,motor,item):
        from arena_privileged_geometry import capsule_quad
        radius,half=self.pickup_profile
        support=self.surface(motor,0.)
        theta=math.atan(support.slope)if support and motor.mode in REST else 0.
        co,si=math.cos(theta),math.sin(theta)
        rotation=np.array([[co,-si],[si,co]])
        center=np.array([motor.x+motor.offset_render,motor.y])
        quad=(np.array([xy(p)for p in item['colliders'][0]['quad']])-center)@rotation
        return float(capsule_quad(np.array([[0.,0.,radius,half]]),quad[None,:,:],np.array([True]))[0])

    def spring_launch(self,motor,contact,used,stamp):
        hits=[]
        for item in self.spring_launches:
            if item['id']in used:continue
            distance=self.spring_distance(contact,item)
            guard=.0002+4*abs(float(np.spacing(np.float32(self.observation['state']['time']))))*max(abs(motor.vx),1.)
            if abs(distance)<=guard:return False
            if distance<0:hits.append(item)
        if len(hits)>1:return False
        if hits:
            support=self.surface(contact,0.)
            if support and contact.mode in REST and abs(support.slope)>1e-8:return False
            item=hits[0];p=item['position'];d=item['custom'];used.add(item['id'])
            motor.x=motor.previous_x=motor.physical_x=p['x'];motor.y=motor.previous_y=motor.physical_y=p['y']
            motor.mode='popup';motor.vx=d['_popSpeed'];motor.vy=0.;motor.used=0
            motor.offset_field=motor.offset_render=0.;motor.ground_source=False
            motor.native_air=motor.native_transfer=False;motor.delay=motor.collider_delay=0.
            motor.spring_ready=True;motor.spring_accel=d['_popAcceleration'];motor.spring_event=stamp
        return True

    def surface(self, motor, t):
        contact_x=motor.x+motor.offset_render
        available = [s for s in self.surfaces if s.contains(contact_x, t)]
        current = next((s for s in available if s.id == motor.support), None)
        if current is not None:
            return current
        # GroundCollider may still reference the segment just left. Transfer
        # only to a geometrically connected segment, never an extrapolated line.
        previous = next((s for s in self.surfaces if s.id == motor.support), None)
        if previous:
            connected = [s for s in available if
                         abs(s.height(contact_x,t)-previous.height(contact_x,t))<.05 or
                         abs(s.right-previous.left)<.001 and abs(s.height(s.right,t)-previous.height(previous.left,t))<.001 or
                         abs(s.left-previous.right)<.001 and abs(s.height(s.left,t)-previous.height(previous.right,t))<.001]
            if connected:
                return min(connected, key=lambda s: abs(s.height(contact_x,t)-previous.height(contact_x,t)))
        return None

    def ground_step_surface(self,motor,t):
        current=next((s for s in self.surfaces if s.id==motor.support),None)
        if current and current.platform:
            # GetGroundYIncludeAir queries the restored physical root before
            # this fixed update, not the interpolated render point. Keeping
            # the old platform for one more tick changes a down key into a
            # ground slide instead of the original airborne return.
            x=motor.physical_x+motor.offset_render
            if current.contains(x,t):return current
            below=[s for s in self.surfaces if not s.platform and s.contains(x,t)]
            native=next((s for s in below if s.id==self.observation.get('support_id')),None)
            return native or (below[0]if len(below)==1 else None)
        lengthen=self.rules.get('ground_lengthen')
        if current and lengthen is not None:
            following=next((s for s in self.surfaces if s.id!=current.id and
                abs(s.left-current.right)<.001 and
                abs(s.height(s.left,t)-current.height(current.right,t))<.001),None)
            if following:
                return following if motor.physical_x+motor.offset_render>=following.left+lengthen else current
        return self.surface(replace(motor,x=motor.physical_x,y=motor.physical_y),t)

    def terrain_clearances(self,motors):
        """Keep planned paths out of native wall/automatic-climb transitions.

        Ninja.MoveLogic examines the next vertical link within climbDistance
        using the role-object position, not the hurt capsule's bottom. A high
        link can kill a grounded role before it even reaches the wall. Until
        automatic climb is separately validated, require crossing above the
        link: this is a conservative planning restriction, not new game damage.
        Descending links remain actual finite-support/free-fall transitions.
        """
        distance=np.full(len(motors),math.inf)
        for row in rows(self.observation.get('terrain')):
            a,b=row['start'],row['finish']
            kind=phase(row['kind'])
            reach=self.data.get('_climbDistance',0.)
            for i,m in enumerate(motors):
                x=m.x+m.offset_render
                if kind=='link' and abs(b['x']-a['x'])<.0001 and b['y']>a['y'] and abs(x-a['x'])<=reach:
                    distance[i]=min(distance[i],m.y-b['y'])
                elif kind=='ground' and a['x']-reach<=x<=b['x']:
                    # Same-height rope -> ground is also a wall for a role
                    # hanging underneath. Native movement clamps at left minus
                    # climbDistance; the scrolling camera then kills it. It is
                    # never a traversable continuation of runOnLineDown.
                    height=a['y']+(b['y']-a['y'])*(max(a['x'],x)-a['x'])/max(.0001,b['x']-a['x'])
                    distance[i]=min(distance[i],m.y-height)
                if row.get('death_offset_y') and a['x']-reach<=x<=b['x']:
                    # Ninja.CheckIsDieTerrain uses mean endpoint Y + offset,
                    # rather than the point's interpolated slope height.
                    limit=(a['y']+b['y'])/2+row['death_offset_y']
                    distance[i]=min(distance[i],m.y-limit)
        return distance

    def interaction_bodies(self,motors):
        return np.array([(m.x+m.offset_render,m.y,self.interaction_radius,0.) for m in motors])

    def ground_samples(self,motor,t):
        motor.physical_y=motor.previous_y=motor.y
        motor.ground_source=True

    def action(self, motor, action, t):
        if motor.mode in POP:
            # This reducer only covers the original no-jump launch interval.
            # Enabling pop jump/interrupt needs its own UI transition proof.
            return False
        s = self.surface(motor, t)
        before_mode = motor.mode
        before_vy = motor.vy
        age = (self.clock_age+t)%self.tick
        entry_delay = 2*self.tick-age
        if action == 'jump':
            if motor.mode=='slideonground':
                # Current reducer validates a complete slide/recovery. Native
                # jump interruption still needs an independent source probe.
                return False
            motor.ground_source=False
            if motor.mode in ('runonlinedown', 'rolltolinedown') and s and s.rope:
                motor.mode = 'rolltolineon'; motor.delay = entry_delay
                fast = motor.y > s.height(motor.x+motor.offset_render,t)+self.foot
                motor.transfer_speed = (-self.data['_rollAirDownUpSpeed'] if fast
                                        else self.data['_rollDownUpSpeed'])
            elif motor.mode in AIR and motor.used < 2 or motor.mode in ('runonline', 'runonground', 'slideonground'):
                motor.native_air=self.native_samples and (motor.mode in REST or motor.native_air)
                motor.used = motor.used+1 if motor.mode in AIR else 1
                motor.vy = self.data['_jumpForce2' if motor.used == 2 else '_jumpForce1']
                motor.mode = 'jump2' if motor.used == 2 else 'jump'
                motor.delay = entry_delay
            else:
                return False
        elif action == 'down':
            if motor.mode in ('runonline','rolltolineon') or motor.mode in AIR:
                if s is None:
                    return False
                if motor.mode == 'rolltolineon' and 'reverse_fast_enabled' not in self.rules:
                    return False
                motor.mode = 'rolltolinedown' if s.rope else 'rolltoground'
                motor.delay = entry_delay
                fast = before_mode in AIR or (before_mode=='rolltolineon' and self.rules['reverse_fast_enabled']
                       and motor.y>s.height(motor.x+motor.offset_render,t)+self.foot+self.rules['reverse_fast_offset'])
                motor.transfer_speed = self.data['_rollAirDownUpSpeed' if fast else '_rollDownUpSpeed']
            elif motor.mode == 'runonground':
                if 'slide_seconds' not in self.rules:
                    return False
                if not motor.ground_source:self.ground_samples(motor,t)
                motor.mode='slideonground';motor.delay=entry_delay
                motor.slide_ticks=timer_ticks(self.rules['slide_seconds'],self.tick,False)
                motor.ground_source=True
            else:
                return False
        else:
            return False
        motor.native_transfer=self.native_samples and motor.mode in TRANSFER and (before_mode in REST or motor.native_air or motor.native_transfer)
        if motor.mode not in AIR:motor.native_air=False
        if motor.mode not in REST:
            motor.ground_source=False
        motor.lead_mode = before_mode; motor.lead_vy = before_vy
        number = 2 if before_mode in ('jump2','fall2') else 1
        motor.lead_gravity = self.data[f'_upGravity{number}' if before_vy>0 else f'_downGravity{number}']*3.5 if before_mode in AIR else 0.
        motor.collider_delay = self.tick-age
        motor.elapsed = 0.
        return True

    def body_at(self, m):
        p, scale = self.parameters, self.scale
        mode = m.lead_mode if m.collider_delay > 1e-8 else m.mode
        if mode=='slideonground':
            offset=p['_slideColliderOffset']
            radius=p['_normalColliderRadius']*max(abs(scale['x']),abs(scale['z']))
            support=next((s for s in self.surfaces if s.id==m.support),None)
            angle=math.atan(support.slope)if support else 0.
            ox,oy=offset['x']*scale['x'],offset['y']*scale['y']
            return (m.x+m.offset_render+ox*math.cos(angle)-oy*math.sin(angle),
                    m.y+ox*math.sin(angle)+oy*math.cos(angle),radius,0.)
        if mode in TRANSFER or mode == 'jump2':
            radius = p['_rollColliderRadius']*max(abs(scale['x']), abs(scale['z']))
            # The original roll rotates its offset center. Bound that native
            # local offset instead of assuming its center stays at the root.
            off = p['_rollColliderOffset']
            radius += math.hypot(off['x']*scale['x'], off['y']*scale['y'])
            return (m.x+m.offset_render, m.y, radius, 0.)
        jumping = mode == 'jump'
        offset = p['_jumpColliderOffset' if jumping else '_normalColliderOffset']
        height = p['_jumpColliderHeight' if jumping else '_normalColliderHeight']*abs(scale['y'])
        radius = p['_normalColliderRadius']*max(abs(scale['x']), abs(scale['z']))
        half=max(0.,height/2-radius)
        support=next((s for s in self.surfaces if s.id==m.support),None)
        angle=math.atan(support.slope) if mode in REST and support else 0.
        cosine,sine=math.cos(angle),math.sin(angle)
        ox,oy=offset['x']*scale['x'],offset['y']*scale['y']
        # Enclose the original tilted capsule with the planning layer's vertical
        # capsule. Retain the rotated native local center; no visual box fitting.
        return (m.x+m.offset_render+ox*cosine-oy*sine,m.y+ox*sine+oy*cosine,
                radius+abs(half*sine),half*abs(cosine))

    def trajectory(self, times, operations=()):
        if not self.native_samples or len(times)<2:
            return self._trajectory(times,operations)
        # Preserve the original fixed-step lattice even for sparse audit times.
        # Every inner interval contains at most one native update and each key
        # is consumed at its own time, independent of the requested output grid.
        times=np.asarray(times,dtype=float)
        fixed=np.arange(1,math.ceil((self.clock_age+times[-1])/self.tick)+1)*self.tick-self.clock_age
        knots=np.unique(np.concatenate((times,fixed[(fixed>times[0])&(fixed<times[-1])],
            np.array([t for t,_ in operations if times[0]<=t<=times[-1]],dtype=float))))
        body,states,valid=self._trajectory(knots,operations)
        indices=np.searchsorted(knots,times)
        return body[indices],[states[i]for i in indices],valid

    def _trajectory(self, times, operations=()):
        motor = replace(self.initial)
        states, bodies, valid = [], [], True
        operation = 0
        used_springs=set()
        for index, t in enumerate(times):
            if index:
                dt = t-times[index-1]
                old_fixed=int(math.floor((self.clock_age+times[index-1]+1e-8)/self.tick))
                new_fixed=int(math.floor((self.clock_age+t+1e-8)/self.tick))
                if self.spring_launches and new_fixed>old_fixed:
                    contact=replace(motor,x=motor.physical_x,y=motor.physical_y)
                    valid &= self.spring_launch(motor,contact,used_springs,float(t))
                pending_air=(motor.native_air and motor.mode in AIR or motor.native_transfer and motor.mode in TRANSFER) and motor.delay>self.tick+1e-8
                pending_slide=self.native_samples and motor.mode=='slideonground'and motor.delay>self.tick+1e-8
                effective_mode=motor.lead_mode if pending_air or pending_slide else motor.mode
                if motor.ground_source and motor.mode in REST or pending_air and motor.lead_mode in REST:
                    if new_fixed>old_fixed:
                        s=self.ground_step_surface(motor,t)
                    else:
                        s=next((s for s in self.surfaces if s.id==motor.support),None)
                else:
                    s = self.surface(motor, t)
                departing_platform=(self.native_samples and new_fixed>old_fixed and
                    any(a.id==motor.support and a.platform for a in self.surfaces)and
                    (s is None or s.id!=motor.support))
                if departing_platform and motor.delay>self.tick+1e-8 and motor.lead_mode in REST:
                    # The old physics update changes the input prerequisite
                    # before the queued UI key is consumed. Until that queued
                    # transition has its own native pairing, reject it rather
                    # than predicting a ground slide after stepping off.
                    valid=False
                if s and motor.mode=='runonline' and not s.rope and not departing_platform:
                    motor.mode='runonground'
                    if not motor.ground_source:self.ground_samples(motor,t)
                elif s and motor.mode=='runonground' and s.rope and not departing_platform:
                    motor.mode='runonline'
                natural_departure=False;departure_mode=''
                if (self.native_samples and new_fixed>old_fixed and motor.mode in REST and
                        motor.mode!='slideonground' and not pending_air and
                        (departing_platform or s is None or not s.rope and abs(s.slope)<1e-8 and s.id!=motor.support and
                         motor.physical_y>s.height(motor.physical_x+motor.offset_render,t)+self.foot+1e-5)):
                    # MoveLogic cached UpdateGravity before this ground
                    # reducer changes state. Its first FallFromRun still
                    # uses the old zero ground gravity, even across a gap
                    # where surface() cannot bind the lower terrain yet.
                    natural_departure=True
                    previous_support=next((a for a in self.surfaces if a.id==motor.support),None)
                    if previous_support and abs(previous_support.slope)<1e-8:departure_mode=motor.mode
                    motor.mode='fallfromrun';motor.ground_source=False;motor.native_air=True
                    if s:motor.support=s.id
                    effective_mode=motor.mode
                slope = s.slope if s and effective_mode in REST else 0.
                # Native SlopeSpeedRatio: speed along a slope, rather than a
                # horizontal velocity plus an unrelated vertical correction.
                ratio = 1/math.sqrt(1+slope*slope)
                vx = self.speed*ratio
                slide_entered=motor.mode=='slideonground' and motor.delay<=dt+1e-8
                active_slope=bool(s and abs(s.slope)>1e-8 and
                    (effective_mode=='runonground'or slide_entered and s.slope<0))
                if motor.mode in POP:
                    if motor.mode=='popup':
                        for _ in range(new_fixed-old_fixed):
                            v=np.float32(motor.vx);a=np.float32(motor.spring_accel if v<self.data['_moveSpeed']else-motor.spring_accel)
                            motor.vx=float(np.float32(v+np.float32(np.float32(np.float32(v*a)*v)*np.float32(self.tick))))
                    vx=motor.vx
                elif active_slope:
                    # ProcessMovementOnGround accelerates the velocity's
                    # magnitude on a descent, then projects onto its segment.
                    # SlopeSpeedRatio is a target multiplier, not horizontal VX.
                    magnitude=math.hypot(motor.vx,motor.lead_vy if pending_air else motor.vy)
                    descent=max(0.,-s.slope/math.sqrt(1+s.slope*s.slope))
                    for _ in range(new_fixed-old_fixed):
                        if descent:
                            target=(self.data['_moveSpeed']+self.shell_dash_speed)*(1+2*descent)
                            magnitude=float(np.float32(np.float32(magnitude)+np.float32(
                                np.float32(target-np.float32(magnitude))*np.float32(self.tick))))
                        else:
                            magnitude=self.data['_moveSpeed']+self.shell_dash_speed
                    vx=magnitude*ratio;motor.vx=vx
                    if not (motor.ground_source or pending_air):
                        valid=False
                elif s and s.rope:
                    for _ in range(new_fixed-old_fixed):
                        motor.vx=float(np.float32(np.float32(motor.vx)+np.float32(
                            np.float32(self.speed-np.float32(motor.vx))*np.float32(self.tick*5))))
                    vx=motor.vx
                elif motor.native_air and motor.mode in AIR:
                    vx=motor.vx
                elif slide_entered:
                    magnitude=math.hypot(motor.vx,motor.vy)
                    for _ in range(new_fixed-old_fixed):
                        # Original cubic speed target and Lerp(dt*5), not a
                        # fitted constant slide speed or ordinary run speed.
                        speed=np.float32(self.speed)
                        a=np.float32(np.float32(speed*np.float32(.00325))*speed)
                        b=np.float32(speed*np.float32(-.167))
                        target=np.float32(speed*np.float32(np.float32(a+b)+np.float32(3.14)))
                        magnitude=float(np.float32(np.float32(magnitude)+np.float32(
                            np.float32(target-np.float32(magnitude))*np.float32(self.tick*5))))
                        motor.vx=magnitude*ratio
                    vx=motor.vx
                elif motor.ground_source and not new_fixed-old_fixed:
                    vx=motor.vx
                else:
                    motor.vx=vx
                if slide_entered:
                    motor.slide_ticks-=new_fixed-old_fixed
                    if motor.slide_ticks<=0:motor.mode='runonground'
                for _ in range(new_fixed-old_fixed):
                    # Ninja.MyFixedUpdate positions the collider parent from
                    # the preceding offset before MoveLogic changes its field.
                    motor.offset_render=motor.offset_field
                    if slide_entered and motor.mode=='runonground':
                        # ProcessMovementOnGround advances the slide offset
                        # before its final timer changes mode to ground.
                        # MoveLogic then also advances the ordinary offset.
                        sine=-s.slope/math.sqrt(1+s.slope*s.slope)if s else 0.
                        so=min(10.,32*sine)if sine>0 else 16*sine
                        target=(self.rules['slide_offset']['x']+so)*self.scale['x']
                        if abs(motor.offset_field)<abs(target):
                            motor.offset_field=float(np.float32(np.float32(motor.offset_field)+np.float32(
                                np.float32(target-motor.offset_field)*np.float32(self.tick*5))))
                    if motor.mode=='slideonground' and slide_entered:
                        sine=-s.slope/math.sqrt(1+s.slope*s.slope)if s else 0.
                        slope_offset=min(10.,32*sine)if sine>0 else 16*sine
                        target=(self.rules['slide_offset']['x']+slope_offset)*self.scale['x']
                        gain=self.tick*5 if abs(motor.offset_field)<abs(target)else 0.
                    elif effective_mode in REST or departure_mode in REST:
                        slope_offset=0.
                        offset_surface=s if active_slope or slide_entered and motor.mode=='runonground'else None
                        if effective_mode=='runonline' and s and s.rope:
                            # OnLine can hand over the ground reference after
                            # movement, before MoveLogic's final offset tween.
                            post_x=motor.physical_x+vx*self.tick+motor.offset_render
                            offset_surface=next((a for a in self.surfaces if not a.rope and
                                abs(a.left-s.right)<.001 and
                                abs(a.y-s.height(s.right,t))<.001 and
                                post_x>=a.left+self.rules.get('ground_lengthen',0.)),None)
                        if offset_surface:
                            sine=-offset_surface.slope/math.sqrt(1+offset_surface.slope*offset_surface.slope)
                            slope_offset=min(10.,32*sine) if sine>0 else 16*sine
                        target=slope_offset*self.scale['x'];gain=self.tick*self.data['_moveSpeed']/10
                        # The UI key changes the native mode during this
                        # first update. ProcessMovementOnGround's preceding
                        # slope tween already ran; MoveLogic's final ordinary
                        # ground-offset tween no longer runs in slide mode.
                        if pending_slide:gain=0.
                    else:
                        continue
                    if not pending_air:
                        motor.offset_field=float(np.float32(np.float32(motor.offset_field)+np.float32(
                            np.float32(target-motor.offset_field)*np.float32(gain))))
                    if active_slope and effective_mode=='runonground':
                        # The same native target receives the additional
                        # iTween.Vector3Update in ProcessMovementOnGround.
                        # Its speed is slopeOffset.x/20, including a negative
                        # value uphill; iTween does not clamp this gain.
                        motor.offset_field=float(np.float32(np.float32(motor.offset_field)+np.float32(
                            np.float32(target-motor.offset_field)*np.float32(self.tick*slope_offset/20))))
                for _ in range(new_fixed-old_fixed):
                    motor.previous_x=motor.physical_x
                    motor.physical_x=float(np.float32(np.float32(motor.physical_x)+np.float32(vx*self.tick)))
                alpha=np.clip((self.clock_age+t-new_fixed*self.tick)/self.tick,0.,1.)
                motor.x=motor.previous_x+(motor.physical_x-motor.previous_x)*alpha
                if not (motor.ground_source and motor.mode in REST):
                    s = self.surface(motor, t)
                if motor.mode in REST:
                    if s:
                        if motor.mode=='runonline' and not s.rope:
                            motor.mode='runonground'
                            if not motor.ground_source and abs(s.slope)<1e-8:
                                self.ground_samples(motor,t)
                        contact=(-self.foot if motor.mode=='runonlinedown' else self.foot-.25 if
                                 slide_entered else self.foot)
                        if effective_mode=='runonground' and abs(s.slope)>1e-8:
                            contact=self.foot*math.sqrt(1+s.slope*s.slope)
                        target_y=s.height((motor.physical_x if motor.ground_source else motor.x)+motor.offset_render,t)+contact
                        if motor.ground_source:
                            for _ in range(new_fixed-old_fixed):
                                motor.previous_y=motor.physical_y;motor.physical_y=target_y
                            alpha=np.clip((self.clock_age+t-new_fixed*self.tick)/self.tick,0.,1.)
                            motor.y=motor.previous_y+(motor.physical_y-motor.previous_y)*alpha
                        else:
                            motor.y=target_y
                        motor.support = s.id; motor.used = 0; motor.vy = vx*s.slope+s.vy
                    else:
                        motor.mode = 'fallfromrun'; motor.vy = vx*slope
                        motor.ground_source=False
                elif motor.mode in POP:
                    valid &= motor.spring_ready
                    for _ in range(new_fixed-old_fixed):
                        motor.previous_y=motor.physical_y
                        # The first PopUp uses _downGravity1 and its one
                        # quadratic VX update above. Once descending, the
                        # original PopFall keeps VX and uses _downGravity3.
                        was_popup=motor.mode=='popup'
                        gravity=np.float32(np.float32(self.data['_downGravity1'if was_popup else'_downGravity3'])*np.float32(self.tick))
                        gravity=np.float32(gravity*np.float32(3.5))
                        motor.vy=max(-40.,float(np.float32(np.float32(motor.vy)+gravity)))
                        next_y=float(np.float32(np.float32(motor.physical_y)+np.float32(motor.vy*self.tick)))
                        cx=motor.physical_x+motor.offset_render
                        supports=[a for a in self.surfaces if a.contains(cx,t)and not a.platform]
                        # ProcessPopFallNormal uses the integrated position,
                        # unlike the ordinary fall's pre-step landing test.
                        support=next((a for a in supports if a.id==motor.support),None)
                        if support is None and supports:support=max(supports,key=lambda a:a.height(cx,t))
                        if support and abs(support.slope)>1e-8:
                            valid=False
                        if support and not was_popup and next_y<=support.height(cx,t)+self.foot:
                            motor.physical_y=support.height(cx,t)+self.foot
                            motor.mode='runonline'if support.rope else'runonground'
                            motor.used=0;motor.support=support.id;motor.vy=0.;motor.ground_source=True
                        else:motor.physical_y=next_y
                        if was_popup and motor.vy<0:motor.mode='popfall'
                    motor.y=motor.previous_y+(motor.physical_y-motor.previous_y)*alpha
                elif motor.mode in TRANSFER:
                    if s is None:
                        valid = False
                    elif motor.native_transfer:
                        for _ in range(new_fixed-old_fixed):
                            motor.previous_y=motor.physical_y
                            if pending_air:
                                if motor.lead_mode in AIR:
                                    number=2 if motor.lead_mode in ('jump2','fall2') else 1
                                    g=self.data[f'_upGravity{number}' if motor.lead_vy>0 else f'_downGravity{number}']*3.5
                                    if motor.lead_mode=='fallfromrun':g=self.data['_downGravity1']*3.5
                                    motor.lead_vy=float(np.float32(np.float32(motor.lead_vy)+np.float32(g*self.tick)))
                                    motor.physical_y=float(np.float32(np.float32(motor.physical_y)+np.float32(motor.lead_vy*self.tick)))
                                elif motor.lead_mode in REST:
                                    motor.physical_y=s.height(motor.physical_x+motor.offset_render,t)+(-self.foot if motor.lead_mode=='runonlinedown' else self.foot)
                                else:
                                    motor.physical_y=float(np.float32(np.float32(motor.physical_y)+np.float32(motor.lead_vy*self.tick)))
                            else:
                                top=motor.mode=='rolltolineon'
                                target=s.height(motor.previous_x+motor.offset_render,t)+(self.foot if top or not s.rope else -self.foot)
                                speed=motor.transfer_speed or (motor.vy if top else abs(motor.vy)) or self.data['_rollDownUpSpeed']
                                next_y=float(np.float32(np.float32(motor.physical_y)+np.float32((speed if top else -speed)*self.tick)))
                                # ProcessMovementOnLine's up-flip checks the
                                # integrated position (strictly past target),
                                # including its fast downward return. The
                                # down-flip has a different settling branch.
                                arrived=((next_y>target if speed>0 else next_y<target) if top
                                         else motor.previous_y<=target)
                                if arrived:
                                    motor.physical_y=s.height(motor.physical_x+motor.offset_render,t)+(self.foot if top or not s.rope else -self.foot)
                                    motor.mode=('runonline' if top else 'runonlinedown') if s.rope else 'runonground'
                                    motor.used=0;motor.support=s.id;motor.vy=0.;motor.ground_source=True;motor.native_transfer=False
                                else:
                                    motor.vy=speed if top else -speed
                                    motor.physical_y=next_y
                        motor.y=motor.previous_y+(motor.physical_y-motor.previous_y)*alpha
                    elif motor.delay > 0:
                        if motor.lead_mode in AIR:
                            motor.y += motor.lead_vy*dt+.5*motor.lead_gravity*dt*dt
                            motor.lead_vy += motor.lead_gravity*dt
                        elif motor.lead_mode in REST:
                            motor.y = s.height(motor.x+motor.offset_render,t)+(-self.foot if motor.lead_mode=='runonlinedown' else self.foot)
                        elif motor.lead_mode in TRANSFER:
                            destination=s.height(motor.x+motor.offset_render,t)+(self.foot if motor.lead_mode=='rolltolineon'else -self.foot if s.rope else self.foot)
                            move=motor.lead_vy*dt
                            motor.y += math.copysign(min(abs(destination-motor.y),abs(move)),move) if move else 0.
                    else:
                        top = motor.mode == 'rolltolineon'
                        target = s.height(motor.x+motor.offset_render,t)+(self.foot if top or not s.rope else -self.foot)
                        speed = abs(motor.transfer_speed) or abs(motor.vy) or self.data['_rollDownUpSpeed']
                        delta = target-motor.y
                        motor.vy = math.copysign(speed, delta)
                        motor.y += math.copysign(min(abs(delta), speed*dt), delta)
                        if abs(delta) <= speed*dt:
                            motor.mode = ('runonline' if top else 'runonlinedown') if s.rope else 'runonground'
                            motor.used = 0; motor.support = s.id;motor.vy=0.
                            if not s.rope and abs(s.slope)<1e-8:
                                self.ground_samples(motor,t)
                elif motor.mode in AIR:
                    if motor.native_air:
                        for _ in range(new_fixed-old_fixed):
                            motor.previous_y=motor.physical_y
                            if pending_air and motor.lead_mode in REST and s:
                                contact=self.foot*math.sqrt(1+s.slope*s.slope) if not s.rope else self.foot
                                motor.physical_y=s.height(motor.physical_x+motor.offset_render,t)+contact
                            elif pending_air:
                                # The key is consumed after this physics update.
                                number=2 if motor.lead_mode in ('jump2','fall2') else 1
                                g=self.data[f'_upGravity{number}' if motor.lead_vy>0 else f'_downGravity{number}']*3.5
                                motor.lead_vy=float(np.float32(np.float32(motor.lead_vy)+np.float32(g*self.tick)))
                                motor.physical_y=float(np.float32(np.float32(motor.physical_y)+np.float32(motor.lead_vy*self.tick)))
                            else:
                                was_descending=motor.vy<=0
                                number=2 if motor.used==2 else 1
                                g=self.data[f'_upGravity{number}' if motor.vy>0 else f'_downGravity{number}']*3.5
                                if motor.mode=='fallfromrun':g=0. if natural_departure else self.data['_downGravity1']*3.5
                                motor.vy=max(-40.,float(np.float32(np.float32(motor.vy)+np.float32(g*self.tick))))
                                motor.physical_y=float(np.float32(np.float32(motor.physical_y)+np.float32(motor.vy*self.tick)))
                                if motor.vy<=0:
                                    motor.mode='fall2' if motor.used==2 else 'fall' if motor.used else 'fallfromrun'
                                    cx=motor.physical_x+motor.offset_render
                                    # The ground lookup at function entry uses the
                                    # pre-step point. A new floor reached by the
                                    # integrated X cannot land the role one tick
                                    # before the original ground reference.
                                    contacts=[a for a in self.surfaces if a.contains(motor.previous_x+motor.offset_render,t) and
                                        # LevelManager.GetGroundY excludes an
                                        # AirGround whose top is above the
                                        # actor's pre-step root Y. Ordinary
                                        # terrain uses a different lookup.
                                        (not a.platform or motor.previous_y>=a.height(motor.previous_x+motor.offset_render,t)) and
                                        motor.previous_y<=a.height(motor.previous_x+motor.offset_render,t)+self.foot] if was_descending else []
                                    # The jump reducer only changes to fall on
                                    # its first descending tick; the original
                                    # fall reducer lands on the following tick.
                                    if contacts:
                                        a=max(contacts,key=lambda a:a.height(cx,t))
                                        if not a.rope:
                                            landing_speed=self.data['_moveSpeed']+self.shell_dash_speed
                                            if a.slope<0:
                                                descent=-a.slope/math.sqrt(1+a.slope*a.slope)
                                                landing_speed=float(np.float32(np.float32(landing_speed)+np.float32(np.float32(landing_speed*2*descent)*np.float32(self.tick))))
                                            motor.vx=landing_speed/math.sqrt(1+a.slope*a.slope)
                                            motor.physical_x=float(np.float32(np.float32(motor.previous_x)+np.float32(motor.vx*self.tick)))
                                            cx=motor.physical_x+motor.offset_render
                                            motor.x=motor.previous_x+(motor.physical_x-motor.previous_x)*alpha
                                        contact=self.foot*math.sqrt(1+a.slope*a.slope) if not a.rope else self.foot
                                        motor.physical_y=a.height(cx,t)+contact
                                        motor.mode='runonline' if a.rope else 'runonground'
                                        motor.used=0;motor.support=a.id;motor.native_air=False;motor.ground_source=True
                                        motor.vy=motor.vx*a.slope+a.vy
                                        sine=-a.slope/math.sqrt(1+a.slope*a.slope)
                                        off=(min(10.,32*sine) if sine>0 else 16*sine)*self.scale['x']
                                        for gain in (self.tick*self.data['_moveSpeed']/10,):
                                            motor.offset_field=float(np.float32(np.float32(motor.offset_field)+np.float32(
                                                np.float32(off-motor.offset_field)*np.float32(gain))))
                        motor.y=motor.previous_y+(motor.physical_y-motor.previous_y)*alpha
                    elif motor.delay > 0:
                        if motor.lead_mode in REST and s:
                            motor.y = s.height(motor.x+motor.offset_render,t)+self.foot
                        elif motor.lead_mode in AIR:
                            motor.y += motor.lead_vy*dt+.5*motor.lead_gravity*dt*dt
                            motor.lead_vy += motor.lead_gravity*dt
                    else:
                        before = motor.y
                        number = 2 if motor.used == 2 else 1
                        gravity = self.data[f'_upGravity{number}' if motor.vy > 0 else f'_downGravity{number}']*3.5
                        if motor.mode == 'fallfromrun':
                            gravity = self.data['_downGravity1']*3.5
                        motor.y += motor.vy*dt + .5*gravity*dt*dt
                        motor.vy = max(-40., motor.vy+gravity*dt)
                        if motor.vy <= 0:
                            motor.mode = 'fall2' if motor.used == 2 else 'fall' if motor.used else 'fallfromrun'
                            contact_x=motor.x+motor.offset_render
                            contacts = [a for a in self.surfaces if a.contains(contact_x,t)
                                        and before >= a.height(contact_x,t)+self.foot-.01
                                        and motor.y <= a.height(contact_x,t)+self.foot]
                            if contacts:
                                a = max(contacts,key=lambda a:a.height(contact_x,t))
                                motor.y = a.height(contact_x,t)+self.foot
                                motor.mode = 'runonline' if a.rope else 'runonground'
                                motor.used = 0; motor.vy = 0.; motor.support = a.id
                                if not a.rope and abs(a.slope)<1e-8:
                                    self.ground_samples(motor,t)
                motor.delay -= dt; motor.collider_delay -= dt; motor.elapsed += dt
            while operation < len(operations) and operations[operation][0] <= t+1e-8:
                valid &= self.action(motor, operations[operation][1], t)
                operation += 1
            states.append(replace(motor))
            if index == 0:
                b = self.body
                radius = min(b['extents']['x'], b['extents']['y'])
                bodies.append((b['center']['x'], b['center']['y'], radius, max(0., b['extents']['y']-radius)))
            else:
                bodies.append(self.body_at(motor))
        return np.asarray(bodies), states, valid


@dataclass
class Hazard:
    id: int | str
    enemy: int
    kind: str
    centers: np.ndarray
    extents: np.ndarray
    active: np.ndarray
    source: str
    approximate: bool = False
    geometry: str = 'aabb'
    quads: np.ndarray | None = None
    interaction: bool = False
    padding: float = 0.


def spider_positions(enemy, times, *, stamp, tick, activation_tick=None):
    """Recovered EnemySpider.ProcessState: drop, elastic flex, then stay.

    _curSpeed/_accUpFlag are current internal state, not fitted velocities.
    Original flex decrements speed by 40*dt, moves down by speed*5*dt,
    then iTween.FloatUpdate uses current+(target-current)*50*deltaTime.
    Preserve the original 20ms Euler steps and BaseObject interpolation;
    smaller numerical steps change this deliberately discrete elastic motion.
    """
    f, custom = enemy['fields'], enemy['custom']
    mode = phase(f['_enemyState']); target = np.float32(f['_targetY'])
    y = np.float32(f['_lastPosition']['y']); previous = np.float32(f['_secondLastPosition']['y'])
    speed = np.float32(f['_curSpeed']); accelerating = f['_accUpFlag']; dt = np.float32(tick)
    age = max(0., min(tick, stamp-f['_lastFixedUpdateTime']))
    offset = enemy['position']['y']-(float(previous)+(float(y)-float(previous))*age/tick)
    steps = 0; ys = []
    for t in times:
        wanted = int(math.floor((age+t+1e-8)/tick))
        while steps < wanted:
            previous = y
            if mode == 'none' and steps+1 == activation_tick:
                # ProcessState's activation branch changes state only. The
                # first downward integration happens on the following tick.
                mode = 'movetoninja'
            elif mode == 'movetoninja':
                y = np.float32(y-np.float32(np.float32(custom['_downSpeed'])*dt))
                if y < target:
                    y = target
                    mode = 'flex'
            elif mode == 'stay':
                y = np.float32(y+np.float32(np.float32(custom['_upSpeed'])*dt))
            elif mode == 'flex':
                if speed > 0 and accelerating:
                    speed = np.float32(speed+np.float32(np.float32(-40.)*dt))
                    y = np.float32(y+np.float32(np.float32(np.float32(-5.)*speed)*dt))
                else:
                    accelerating = False
                    if y < target:
                        desired = np.float32(np.float32(np.float32(target+np.float32(.7))-y)*np.float32(5.))
                        speed = np.float32(speed+np.float32(np.float32(np.float32(desired-speed)*np.float32(50.))*dt))
                        y = np.float32(y+np.float32(speed*dt))
                        if y > target:
                            y = target
                    else:
                        y = target; mode = 'stay'; speed = np.float32(0.)
            steps += 1
        alpha = np.clip((age+t-steps*tick)/tick,0.,1.)
        ys.append(float(previous)+(float(y)-float(previous))*alpha+offset)
    return np.asarray(ys)


def hazard_forecasts(observation, times, player, trajectory_states=None,*,forecast_cache=None):
    """Per-instance original phase clocks, never guessed visual phase ages."""
    result, unsupported = [], []
    speed = observation['role']['data']['_moveSpeed']
    camera = observation.get('camera', {})
    camera_x = camera.get('position', {}).get('x')
    real_right = camera.get('real_right', {}).get('x')
    family_context={}
    if trajectory_states is None and any(e['type']in ('EnemyBullutFireRobot','EnemyBullutLaser','EnemyAlarmShooter','EnemySmallSword','EnemyFlyBamboo')
                                        for e in rows(observation['enemies'])):
        _,coast,valid=player.trajectory(times)
        if valid:trajectory_states=coast
    camera_key=role_x_key=None
    if forecast_cache is not None:
        # One immutable paused observation owns this memo. A new observation
        # (including a restored VM branch) cannot inherit the old world.
        if forecast_cache.get('_observation')is not observation:
            forecast_cache.clear();forecast_cache['_observation']=observation
        if trajectory_states is not None and any(e['type']in ('EnemyBullutFireRobot','EnemyBullutLaser','EnemyAlarmShooter')
                                                 for e in rows(observation['enemies'])):
            from arena_privileged_families import camera_x_bounds
            family_context['camera_x']=camera_x_bounds(observation,times,player,trajectory_states)
            camera_bounds,reason=family_context['camera_x']
            if camera_bounds is not None:
                camera_key=(np.asarray(times).tobytes(),player.tick,player.speed,
                            camera_bounds[0].tobytes(),camera_bounds[1].tobytes())
                role_x_key=np.asarray([(m.physical_x,m.previous_x,m.offset_render)for m in trajectory_states]).tobytes()
    for enemy in rows(observation['enemies']):
        f, custom, kind = enemy['fields'], enemy['custom'], enemy['type']
        if f.get('_dead') or f.get('_isRecycled'):
            continue
        if (kind in ('EnemyFlyBamboo','EnemyBullutFireRobot','EnemyBullutLaser','EnemyAlarmShooter')and
                (player.initial.mode in POP or trajectory_states is not None and any(m.mode in POP for m in trajectory_states))):
            unsupported.append(dict(id=enemy['id'],type=kind,reason='spring_pop_camera_transition_not_validated'))
            continue
        if kind=='EnemyFruitMuppet':
            from arena_privileged_families import collectible_kind
            if not collectible_kind(enemy):
                unsupported.append(dict(id=enemy['id'],type=kind,
                    reason='unverified_fruit_identity_or_damage'))
            continue
        if kind not in ('EnemyBlade','EnemySpiderWeb','EnemyKill','EnemyHideBlade','EnemyBambooWater','EnemyPiranha') and any(
                c.get('depth_tilt') for c in rows(enemy['colliders'])):
            unsupported.append(dict(id=enemy['id'],type=kind,reason='spatial_rotation_requires_3D_forecast'))
            continue
        mode = phase(f.get('_enemyState', f.get('_currState', 'unknown')))
        tick = observation['state']['fixedDeltaTime']
        age = max(0., observation['state']['time']-f.get('_lastFixedUpdateTime',observation['state']['time']))
        colliders = [c for c in rows(enemy['colliders']) if c.get('damage_kind') and c.get('enabled')]
        source, approximate = '', False
        delta = np.zeros((len(times), 2)); growth = np.ones(len(times)); active = np.ones(len(times), bool)
        if kind == 'EnemyStraightBat':
            direction = xy(f.get('_rushDir', dict(x=-1., y=0.)))
            if mode == 'rushtoninja':
                delta = times[:, None]*direction*abs(custom['_rushSpeed'])
                original_scale = f['_oriScale']
                growth[:] = max(1., 1.3*abs(original_scale['x'])/max(abs(enemy['scale']['x']), 1e-6))
            else:
                enter = 0.
                if mode in ('none', 'enterscreen') and camera_x is not None:
                    ideal = max(0., (enemy['position']['x']-camera_x-f['_rushDistance'])/(speed+10))
                    enter = max(0., math.ceil(ideal/tick)*tick-age+tick)
                elif mode not in ('stay', 'ready'):
                    unsupported.append(dict(id=enemy['id'], type=kind, reason='unmapped_phase:'+mode)); continue
                remaining = timer_ticks(f['_currStateTime'] if mode in ('stay','ready') else custom['_stayTime'],tick)*tick
                ready = timer_ticks(.3,tick)*tick if mode != 'ready' else 0.
                launch = enter+remaining+ready+(tick-age if mode in ('stay','ready') else 0.)
                waiting = np.clip(times-enter, 0., remaining+ready)
                if mode in ('stay','ready'):
                    waiting = np.minimum(times,launch)
                flight = np.maximum(0., times-launch)
                if mode in ('none', 'enterscreen'):
                    if trajectory_states is None:
                        _, trajectory_states, _ = player.trajectory(times)
                    ix = min(len(times)-1, int(np.searchsorted(times, enter)))
                    target = np.array([trajectory_states[ix].x, trajectory_states[ix].y])
                    lock_position = xy(enemy['position'])+np.array([-10*enter, 0.])
                    if custom.get('_followNinjaY'):
                        delta[:, 1] = np.where(times >= enter, target[1]-lock_position[1], 0.)
                        lock_position[1] = target[1]
                    if custom.get('_pointToNinja'):
                        direction = target-lock_position
                    else:
                        direction = np.array([-1., custom.get('_rushTargetY',0.)/max(.001, lock_position[0]-target[0])])
                    direction = direction/max(1e-9, np.linalg.norm(direction))
                delta[:, 0] = -10*np.minimum(times, enter)+speed*waiting
                delta += flight[:, None]*direction*abs(custom['_rushSpeed'])
                growth = 1.+.3*np.clip(flight/.06, 0., 1.)
            source = 'EnemyStraightBat.StateUpdate/StayLogic; native remaining timer, direction and instance rushSpeed'
        elif kind == 'EnemyFlyBamboo':
            colliders = [c for c in colliders if c['name'] == 'Attack' and c.get('parent_active', c['active'])]
            if not colliders:
                unsupported.append(dict(id=enemy['id'], type=kind, reason='selected_attack_shape_missing')); continue
            if custom.get('_followNinja'):
                from arena_privileged_families import tracking_bamboo
                predicted,reason=tracking_bamboo(enemy,times,observation,player,trajectory_states)
                if predicted is None:
                    unsupported.append(dict(id=enemy['id'],type=kind,reason=reason));continue
                delta,angles,source,active=predicted[:4];approximate=True
            else:
                remaining = timer_ticks(f['_currStateTime'],tick,mode=='readyattack')*tick
                lock = timer_ticks(custom['_aimLockTime'],tick,False)*tick
                ready = timer_ticks(.5,tick)*tick
                launch = remaining+lock+ready if mode == 'aim' else remaining+ready if mode == 'aimlock' else remaining if mode == 'readyattack' else 0.
                launch = max(0., launch-age)
                if mode not in ('aim', 'aimlock', 'readyattack', 'flytoninja', 'none'):
                    unsupported.append(dict(id=enemy['id'], type=kind, reason='unmapped_phase:'+mode)); continue
                if mode == 'none':
                    continue
                if mode == 'flytoninja':
                    delta[:, 0] = -abs(f['_flySpeed'])*times
                elif camera.get('reflection_right') is not None:
                    # ProcessState's ready phase follows RealRight+.5, but the
                    # *launch* uses ScreenRightTopPos_Reflection(0)+2. The camera
                    # sample is one physics update behind the movement clock.
                    spawn = camera['reflection_right']['x']+speed*(launch-tick+age)+2.
                    movement = launch+tick
                    delta[:, 0] = spawn-enemy['position']['x']-abs(f['_flySpeed'])*np.maximum(0., times-movement)
                else:
                    unsupported.append(dict(id=enemy['id'], type=kind, reason='camera_spawn_missing')); continue
                active = times >= launch
                source = 'EnemyFlyBamboo.ProcessState; native aim/lock/ready remaining timer, real camera edge and flySpeed'
        elif kind in ('EnemySpider', 'EnemyMuppetBomb','EnemyEliteSpider'):
            if kind=='EnemyEliteSpider' and f.get('_positionIndex',0)>0:
                unsupported.append(dict(id=enemy['id'],type=kind,reason='elite_damage_relocation'));continue
            if mode=='bite':
                # TriggerFeedback changes the render child's local position
                # and scale along authored curves; a frozen sphere is wrong.
                unsupported.append(dict(id=enemy['id'],type=kind,reason='spider_bite_feedback_geometry'));continue
            if mode=='none' and kind in ('EnemySpider','EnemyMuppetBomb'):
                from arena_privileged_families import spider_entry
                predicted,reason=spider_entry(enemy,times,observation,player,trajectory_states)
                if predicted is None:
                    unsupported.append(dict(id=enemy['id'],type=kind,reason=reason));continue
                delta[:,1],spread=predicted
                source='EnemySpider.ProcessState; native role-distance activation ticks then original drop/flex envelope'
                approximate=True
            elif mode not in ('movetoninja', 'stay', 'flex'):
                unsupported.append(dict(id=enemy['id'], type=kind, reason='unmapped_phase:'+mode)); continue
            else:
                delta[:, 1] = spider_positions(enemy, times,stamp=observation['state']['time'],tick=tick)-enemy['position']['y']
                source = 'EnemySpider.ProcessState; native targetY/downSpeed/curSpeed/accUpFlag and original flex reducer'
                approximate = mode in ('movetoninja', 'flex')
        else:
            from arena_privileged_families import forecast
            try:
                memo=None
                if camera_key is not None and kind in ('EnemyBullutFireRobot','EnemyBullutLaser','EnemyAlarmShooter'):
                    # Existing bullets depend on camera X only. Pending
                    # non-tracking shots also sample actor X at birth. A
                    # tracking shot must retain Y and is deliberately not
                    # memoized through this horizontal-only dependency key.
                    tracking=kind=='EnemyAlarmShooter'and any(p.get('_pointToNinja')for p in rows(enemy.get('alarm_shooter',{}).get('bullets')))
                    if not tracking:memo=(enemy['id'],kind,camera_key,role_x_key if kind=='EnemyAlarmShooter'else None)
                if memo is not None and memo in forecast_cache:
                    predicted,reason=forecast_cache[memo]
                else:
                    predicted, reason = forecast(enemy, times, observation, player,trajectory_states,context=family_context)
                    if memo is not None:forecast_cache[memo]=(predicted,reason)
            except KeyError as error:
                predicted, reason = None, 'native_field_missing:'+str(error)
            if predicted is None:
                unsupported.append(dict(id=enemy['id'], type=kind, reason=reason)); continue
            delta, angles, source = predicted[:3]
            if len(predicted)>3 and predicted[3] is not None:
                active = predicted[3]
            if kind=='EnemyPiranha':
                colliders=[c for c in rows(enemy['colliders'])if c.get('damage_kind')];approximate=True
            elif kind=='EnemyPoleaxeWarrior':
                from arena_privileged_poleaxe import damage_bindings
                # Its concrete body callback attacks the warrior, unlike the
                # EnemyBase body damage callback. Keep the axe hazardous even
                # beyond a predicted body contact: future melee kills are not
                # yet certified, so this remains a conservative lifetime.
                colliders=[damage_bindings(enemy)[1]];approximate=True
            elif kind=='EnemyBambooWater':
                colliders=predicted[4];approximate=True
            elif kind=='EnemyBrambleCollider':
                colliders=[c for c in rows(enemy['colliders'])if c.get('native_movement_callback')=='bramble_contact']
            elif kind=='EnemyHideBlade':
                colliders = [c for c in rows(enemy['grown_colliders']) if c.get('damage_kind')]
            elif kind=='EnemyArrow' and mode!='onground' and enemy.get('untrimmed_colliders'):
                colliders = [c for c in rows(enemy['untrimmed_colliders']) if c.get('damage_kind')]
        for c in colliders:
            if kind not in ('EnemyFlyBamboo','EnemyHideBlade','EnemyBambooWater','EnemyPoleaxeWarrior','EnemyConnectElectricBall','EnemyRotateElectricBall') and not c['active']:
                continue
            center = xy(c['center'])[None, :]+delta
            extent = np.tile(xy(c['extents']), (len(times), 1))*growth[:, None]
            if kind=='EnemyFlyBamboo'and custom.get('_followNinja'):
                center,extent=predicted[4][c['id']]
            if kind in ('EnemySpider','EnemyMuppetBomb') and mode=='none':
                extent[:,1]+=spread
            if kind=='EnemyRollingBase' and 'envelope_spread'in predicted[5]:
                extent+=predicted[5]['envelope_spread']
            if kind in ('EnemyPinball','EnemyBlowFish') and len(predicted)>4:
                root_scale=np.array([enemy['scale'][a] for a in ('x','y','z')])
                child_scale=np.array([c['scale'][a] for a in ('x','y','z')])/root_scale
                radius=c['radius']*np.max(np.abs(predicted[4]*child_scale),axis=1)
                extent=np.tile(radius[:,None],(1,2))
            elif kind=='EnemyPiranha':
                center=xy(enemy['position'])[None,:]+delta
                extent=np.tile(predicted[4][:,None],(1,2))
            elif kind=='EnemyFruitPinball':
                center=xy(enemy['position'])[None,:]+delta
                radius=c['rotation_envelope']['root_radius']*np.max(np.abs(predicted[4]),axis=1)
                extent=np.tile(radius[:,None],(1,2));approximate=True
                source+='; original rotating collider root-sphere envelope'
            quads = None
            padding=0.
            if kind in ('EnemySpider','EnemyMuppetBomb','EnemyEliteSpider'):
                # Float32 Time/fixedTime subtraction affects interpolation at
                # large absolute clocks; bound it using native travel speed.
                padding=2*abs(float(np.spacing(np.float32(observation['state']['time']))))*max(20.,abs(custom['_downSpeed']))+.00001
            if kind=='EnemyRollingBase':padding=predicted[5]['position_padding'];approximate=True
            if kind=='EnemyPiranha':padding=predicted[5]['position_padding']
            if kind in ('EnemySuspendSpecial','EnemyRotateElectricBall'):
                padding=predicted[5]['position_padding'];approximate=True
            if kind in ('EnemyPoleaxeWarrior','EnemyRockTiger','EnemyConnectElectricBall','EnemyBullutFireRobot','EnemyBullutLaser','EnemyAlarmShooter','EnemyBramblesSingleThorn','EnemyBrambleCollider'):
                center,extent=predicted[4][c['id']]
                approximate=True
            if kind not in ('EnemyStraightBat','EnemyFlyBamboo','EnemySpider','EnemyMuppetBomb','EnemyEliteSpider','EnemyFruitPinball','EnemyPoleaxeWarrior','EnemyPiranha','EnemyRockTiger','EnemyConnectElectricBall','EnemyBullutFireRobot','EnemyBullutLaser','EnemyAlarmShooter','EnemyBramblesSingleThorn','EnemyBrambleCollider'):
                pivot = xy(enemy['position'])
                rot = np.stack((np.stack((np.cos(angles),-np.sin(angles)),axis=-1),
                                np.stack((np.sin(angles),np.cos(angles)),axis=-1)),axis=1)
                center = np.einsum('nij,j->ni', rot, xy(c['center'])-pivot)+pivot+delta
                if c.get('quad'):
                    quad = np.array([xy(p) for p in c['quad']])-pivot
                    quads = np.einsum('nij,kj->nki',rot,quad)+pivot+delta[:,None,:]
                    center = quads.mean(axis=1)
                    extent = (quads.max(axis=1)-quads.min(axis=1))/2
                if kind in ('EnemyHook','EnemyBambooThorn') and len(predicted)>5:
                    if c.get('quad'):
                        lever=np.linalg.norm(np.array([xy(p)for p in c['quad']])-pivot,axis=1).max()
                    else:
                        lever=np.linalg.norm(xy(c['center'])-pivot)+np.linalg.norm(xy(c['extents']))
                    padding=float(lever*predicted[5]['angular_padding']);approximate=True
                elif kind in ('EnemyStraightBack','EnemySmallSword') and len(predicted)>5:
                    padding=float(predicted[5]['position_padding']);approximate=True
            if kind=='EnemySmallSword'and predicted[4]is not None:
                center,extent=predicted[4][c['id']];quads=None;approximate=True
            geometry=('aabb' if kind in ('EnemyAlarmShooter','EnemyBramblesSingleThorn','EnemyBrambleCollider')or kind in ('EnemySpider','EnemyMuppetBomb') and mode=='none' or
                      kind=='EnemyRollingBase' and 'envelope_spread'in predicted[5] else
                      'sphere' if c['type']=='SphereCollider' or kind in ('EnemyFruitPinball','EnemyPiranha') else
                      'obb' if quads is not None else 'aabb')
            result.append(Hazard(c['id'], enemy['id'], kind, center, extent, active, source, approximate,
                                 geometry, quads,
                                 padding=padding,interaction=kind=='EnemyBrambleCollider'))
        if kind in ('EnemyAlarmShooter','EnemyBrambles'):result.extend(predicted[5]['generated_hazards'])
    from arena_privileged_families import pending_enemy_forecasts
    pending,pending_missing=pending_enemy_forecasts(observation,times,player,trajectory_states,family_context)
    result.extend(pending);unsupported.extend(pending_missing)
    for item in player.contact_avoidance:
        for collider in rows(item['colliders']):
            if not collider.get('trigger'):
                continue
            center=np.tile(xy(collider['center']),(len(times),1))
            extent=np.tile(xy(collider['extents']),(len(times),1))
            quads=np.tile(np.array([xy(p)for p in collider['quad']]),(len(times),1,1)) if collider.get('quad') else None
            result.append(Hazard(collider['id'],item['id'],item['type'],center,extent,
                np.ones(len(times),bool),item.get('source','Avoid native ItemSpring pickup; PopBySpring remains unsupported'),
                approximate=True,geometry='obb'if quads is not None else'sphere'if collider['type']=='SphereCollider'else'aabb',
                quads=quads,interaction=True))
    return result, unsupported


def clearance(body, hazard):
    """Conservative capsule/AABB continuous sweep between adjacent samples.

    Original OBBs are currently enclosed by their native world AABB. Rounding
    is retained for SphereCollider/role capsules; no visual boxes are involved.
    """
    if hazard.padding:
        return clearance(body,replace(hazard,padding=0.))-hazard.padding
    if hazard.quads is not None:
        from arena_privileged_geometry import capsule_quad
        return capsule_quad(body,hazard.quads,hazard.active)
    relative = hazard.centers-body[:, :2]
    core = body[:, 3]
    if hazard.geometry == 'sphere':
        distance = np.hypot(relative[:,0],np.maximum(0.,abs(relative[:,1])-core))-(body[:,2]+hazard.extents[:,0])
        a,b = relative[:-1],relative[1:];v=b-a
        length = np.maximum(1e-12,np.sum(v*v,axis=1))
        spine = np.maximum(core[:-1],core[1:])
        minimum = np.minimum(np.hypot(a[:,0],np.maximum(0.,abs(a[:,1])-spine)),
                             np.hypot(b[:,0],np.maximum(0.,abs(b[:,1])-spine)))
        for sign in (-1,1):
            endpoint = np.column_stack((np.zeros(len(spine)),sign*spine))
            t = np.clip(np.sum((endpoint-a)*v,axis=1)/length,0.,1.)
            minimum = np.minimum(minimum,np.linalg.norm(a+t[:,None]*v-endpoint,axis=1))
        crossing = np.divide(-a[:,0],v[:,0],out=np.full(len(v),2.),where=abs(v[:,0])>1e-12)
        y = a[:,1]+np.clip(crossing,0.,1.)*v[:,1]
        minimum = np.where((crossing>=0)&(crossing<=1)&(abs(y)<=spine),0.,minimum)
        radius = np.maximum(body[:-1,2],body[1:,2])+np.maximum(hazard.extents[:-1,0],hazard.extents[1:,0])
        enabled = hazard.active[1:] | hazard.active[:-1]
        distance[1:] = np.minimum(distance[1:],np.where(enabled,minimum-radius,math.inf))
        return np.where(hazard.active|np.r_[False,enabled],distance,math.inf)
    dx = np.maximum(0., abs(relative[:, 0])-hazard.extents[:, 0])
    dy = np.maximum(0., abs(relative[:, 1])-hazard.extents[:, 1]-core)
    distance = np.hypot(dx, dy)-body[:, 2]
    # A fast projectile must not tunnel between samples. The relative segment
    # sweeps against each interval's union of role spine / obstacle extents.
    lo, hi = np.minimum(relative[:-1], relative[1:]), np.maximum(relative[:-1], relative[1:])
    extent = np.maximum(hazard.extents[:-1], hazard.extents[1:])
    radius = np.maximum(body[:-1, 2], body[1:, 2])
    extent[:, 1] += np.maximum(core[:-1], core[1:])
    gap = np.maximum(0., np.maximum(lo-extent, -hi-extent))
    swept = np.hypot(gap[:, 0], gap[:, 1])-radius
    enabled = hazard.active[1:] | hazard.active[:-1]
    distance[1:] = np.minimum(distance[1:], np.where(enabled, swept, math.inf))
    return np.where(hazard.active | np.r_[False, enabled], distance, math.inf)
