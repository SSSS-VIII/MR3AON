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
                              d.get('_speedX', 0.), d.get('_speedY', 0.)))
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
        self.native_slope_ratio = role.get('fields',{}).get('_slopeSpeedRatio')
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
        elif mode=='runonground' and (abs(self.initial.offset_field)>1e-6 or abs(self.initial.offset_render)>1e-6):
            self.initial.ground_source=True
        self.initial.physical_y=role.get('fields',{}).get('_lastPosition',state['position'])['y']
        self.initial.previous_y=role.get('fields',{}).get('_secondLastPosition',state['position'])['y']
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
            self.initial.transfer_speed = abs(role['velocity']['y'])
        self.unsupported = []
        if mode not in REST | AIR | TRANSFER:
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
        for item in rows(observation.get('mechanism_items')):
            dx=item['position']['x']-self.initial.x
            native_static_spring=(item['type']=='ItemSpring' and
                item['fields'].get('_needRotate') is False and
                item['fields'].get('isTrigger') is False and
                not item['fields'].get('beAttracting') and self.interaction_radius>0 and
                any(c.get('trigger') for c in rows(item.get('colliders'))) and
                all(c['type'] in ('BoxCollider','SphereCollider') for c in rows(item.get('colliders'))))
            if native_static_spring:
                self.contact_avoidance.append(item)
                continue
            if -1<dx<self.speed*1.8+3:
                self.unsupported.append('item:'+item['type'])

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

    def action(self, motor, action, t):
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
                motor.transfer_speed = self.data['_rollAirDownUpSpeed' if fast else '_rollDownUpSpeed']
            elif motor.mode in AIR and motor.used < 2 or motor.mode in ('runonline', 'runonground', 'slideonground'):
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
                motor.mode='slideonground';motor.delay=entry_delay
                motor.slide_ticks=timer_ticks(self.rules['slide_seconds'],self.tick,False)
                motor.ground_source=True
            else:
                return False
        else:
            return False
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
            return (m.x+m.offset_render+offset['x']*scale['x'],m.y+offset['y']*scale['y'],radius,0.)
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
        return (m.x+m.offset_render+offset['x']*scale['x'], m.y+offset['y']*scale['y'], radius, max(0., height/2-radius))

    def trajectory(self, times, operations=()):
        motor = replace(self.initial)
        states, bodies, valid = [], [], True
        operation = 0
        for index, t in enumerate(times):
            if index:
                dt = t-times[index-1]
                s = self.surface(motor, t)
                slope = s.slope if s and motor.mode in REST else 0.
                # Native SlopeSpeedRatio: speed along a slope, rather than a
                # horizontal velocity plus an unrelated vertical correction.
                ratio = 1/math.sqrt(1+slope*slope)
                if s and abs(s.slope)>1e-8 and s.id == self.initial.support and motor.mode in REST and self.native_slope_ratio is not None:
                    ratio = self.native_slope_ratio
                vx = self.speed*ratio
                old_fixed=int(math.floor((self.clock_age+times[index-1]+1e-8)/self.tick))
                new_fixed=int(math.floor((self.clock_age+t+1e-8)/self.tick))
                slide_entered=motor.mode=='slideonground' and motor.delay<=dt+1e-8
                if slide_entered:
                    for _ in range(new_fixed-old_fixed):
                        # Original cubic speed target and Lerp(dt*5), not a
                        # fitted constant slide speed or ordinary run speed.
                        speed=np.float32(self.speed)
                        a=np.float32(np.float32(speed*np.float32(.00325))*speed)
                        b=np.float32(speed*np.float32(-.167))
                        target=np.float32(speed*np.float32(np.float32(a+b)+np.float32(3.14)))
                        motor.vx=float(np.float32(np.float32(motor.vx)+np.float32(
                            np.float32(target-np.float32(motor.vx))*np.float32(self.tick*5))))
                        motor.slide_ticks-=1
                    vx=motor.vx*ratio
                    if motor.slide_ticks<=0:
                        motor.mode='runonground'
                elif motor.ground_source and not new_fixed-old_fixed:
                    vx=motor.vx
                else:
                    motor.vx=vx
                for _ in range(new_fixed-old_fixed):
                    # Ninja.MyFixedUpdate positions the collider parent from
                    # the preceding offset before MoveLogic changes its field.
                    motor.offset_render=motor.offset_field
                    if motor.mode=='slideonground' and slide_entered:
                        target=self.rules['slide_offset']['x']*self.scale['x'];gain=self.tick*5
                    elif motor.mode in REST:
                        target=0.;gain=self.tick*self.speed/10
                    else:
                        continue
                    motor.offset_field=float(np.float32(np.float32(motor.offset_field)+np.float32(
                        np.float32(target-motor.offset_field)*np.float32(gain))))
                motor.x += vx*dt
                s = self.surface(motor, t)
                if motor.mode in REST:
                    if s:
                        if motor.mode=='runonline' and not s.rope:
                            motor.mode='runonground'
                        contact=(-self.foot if motor.mode=='runonlinedown' else self.foot-.25 if
                                 motor.mode=='slideonground' and slide_entered else self.foot)
                        target_y=s.height(motor.x+motor.offset_render,t)+contact
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
                elif motor.mode in TRANSFER:
                    if s is None:
                        valid = False
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
                        speed = motor.transfer_speed or abs(motor.vy) or self.data['_rollDownUpSpeed']
                        delta = target-motor.y
                        motor.vy = math.copysign(speed, delta)
                        motor.y += math.copysign(min(abs(delta), speed*dt), delta)
                        if abs(delta) <= speed*dt:
                            motor.mode = ('runonline' if top else 'runonlinedown') if s.rope else 'runonground'
                            motor.used = 0; motor.support = s.id
                elif motor.mode in AIR:
                    if motor.delay > 0:
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
    id: int
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


def spider_positions(enemy, times, *, stamp, tick):
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
            if mode == 'movetoninja':
                y = np.float32(y-np.float32(np.float32(custom['_downSpeed'])*dt))
                if y < target:
                    y = target
                    mode = 'flex'
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
                    else:
                        y = target; mode = 'stay'; speed = np.float32(0.)
            steps += 1
        alpha = np.clip((age+t-steps*tick)/tick,0.,1.)
        ys.append(float(previous)+(float(y)-float(previous))*alpha+offset)
    return np.asarray(ys)


def hazard_forecasts(observation, times, player, trajectory_states=None):
    """Per-instance original phase clocks, never guessed visual phase ages."""
    result, unsupported = [], []
    speed = observation['role']['data']['_moveSpeed']
    camera = observation.get('camera', {})
    camera_x = camera.get('position', {}).get('x')
    real_right = camera.get('real_right', {}).get('x')
    for enemy in rows(observation['enemies']):
        f, custom, kind = enemy['fields'], enemy['custom'], enemy['type']
        if f.get('_dead') or f.get('_isRecycled'):
            continue
        if kind not in ('EnemyBlade','EnemySpiderWeb','EnemyKill','EnemyHideBlade') and any(
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
                unsupported.append(dict(id=enemy['id'], type=kind, reason='tracking_target_y')); continue
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
            if mode not in ('movetoninja', 'stay', 'flex', 'bite'):
                unsupported.append(dict(id=enemy['id'], type=kind, reason='unmapped_phase:'+mode)); continue
            delta[:, 1] = spider_positions(enemy, times,stamp=observation['state']['time'],tick=tick)-enemy['position']['y']
            source = 'EnemySpider.ProcessState; native targetY/downSpeed/curSpeed/accUpFlag and original flex reducer'
            approximate = mode in ('movetoninja', 'flex', 'bite')
        else:
            from arena_privileged_families import forecast
            try:
                predicted, reason = forecast(enemy, times, observation, player,trajectory_states)
            except KeyError as error:
                predicted, reason = None, 'native_field_missing:'+str(error)
            if predicted is None:
                unsupported.append(dict(id=enemy['id'], type=kind, reason=reason)); continue
            delta, angles, source = predicted[:3]
            if len(predicted)>3 and predicted[3] is not None:
                active = predicted[3]
            if kind=='EnemyHideBlade':
                colliders = [c for c in rows(enemy['grown_colliders']) if c.get('damage_kind')]
            elif kind=='EnemyArrow' and mode!='onground' and enemy.get('untrimmed_colliders'):
                colliders = [c for c in rows(enemy['untrimmed_colliders']) if c.get('damage_kind')]
        for c in colliders:
            if kind not in ('EnemyFlyBamboo','EnemyHideBlade') and not c['active']:
                continue
            center = xy(c['center'])[None, :]+delta
            extent = np.tile(xy(c['extents']), (len(times), 1))*growth[:, None]
            if kind in ('EnemyPinball','EnemyBlowFish') and len(predicted)>4:
                root_scale=np.array([enemy['scale'][a] for a in ('x','y','z')])
                child_scale=np.array([c['scale'][a] for a in ('x','y','z')])/root_scale
                radius=c['radius']*np.max(np.abs(predicted[4]*child_scale),axis=1)
                extent=np.tile(radius[:,None],(1,2))
            quads = None
            padding=0.
            if kind not in ('EnemyStraightBat','EnemyFlyBamboo','EnemySpider','EnemyMuppetBomb','EnemyEliteSpider'):
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
                elif kind=='EnemyStraightBack' and len(predicted)>5:
                    padding=float(predicted[5]['position_padding']);approximate=True
            result.append(Hazard(c['id'], enemy['id'], kind, center, extent, active, source, approximate,
                                 'sphere' if c['type']=='SphereCollider' else 'obb' if quads is not None else 'aabb', quads,
                                 padding=padding))
    for item in player.contact_avoidance:
        for collider in rows(item['colliders']):
            if not collider.get('trigger'):
                continue
            center=np.tile(xy(collider['center']),(len(times),1))
            extent=np.tile(xy(collider['extents']),(len(times),1))
            quads=np.tile(np.array([xy(p)for p in collider['quad']]),(len(times),1,1)) if collider.get('quad') else None
            result.append(Hazard(collider['id'],item['id'],item['type'],center,extent,
                np.ones(len(times),bool),'Avoid native ItemSpring pickup; PopBySpring remains unsupported',
                approximate=True,geometry='obb' if quads is not None else 'aabb',quads=quads,interaction=True))
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
