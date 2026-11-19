"""Additional source-derived native motion families, independent of vision.

Registration is a modelling claim, never an acceptance result. Every reducer
requires its actual instance fields; unimplemented variants remain explicit.
"""
import math
import numpy as np


FAMILIES = {
    'EnemyStraightBat': 'native_stay_ready_rush',
    'EnemyFlyBamboo': 'native_aim_lock_launch',
    'EnemySpider': 'native_drop_elastic_flex',
    'EnemyMuppetBomb': 'native_drop_elastic_flex',
    'EnemyBlade': 'stationary_unhit_original_shape',
    'EnemySpiderWeb': 'stationary_original_shape',
    'EnemyDart': 'native_straight_fly_and_render_rotation',
    'EnemySuspend': 'native_wait_vertical_bounce',
    'EnemyCurveBat': 'native_sine_curve',
    'EnemyGhostFire': 'native_sine_curve',
    'EnemyMace': 'native_eccentric_rotation',
    'EnemyHook': 'native_pendulum',
    'EnemyHideBlade': 'native_activation_and_grown_target_envelope',
    'EnemyPinball': 'native_discrete_gravity_and_support_rebound',
    'EnemyBlowFish': 'native_discrete_gravity_and_support_rebound',
    'EnemyBambooThorn': 'native_pendulum',
    'EnemyEliteSpider': 'native_drop_elastic_flex_before_damage_relocation',
    'EnemyEliteDart': 'native_straight_fly_before_death_fall',
    'EnemyFlyFairy': 'native_sine_curve_after_entry_motion',
}


def native_steps(enemy, times, observation, update):
    """Original fixed ticks and BaseObject's one-tick position interpolation."""
    f = enemy['fields']
    tick = observation['state']['fixedDeltaTime']
    age = np.clip(observation['state']['time']-f['_lastFixedUpdateTime'], 0., tick)
    pos = np.array([f['_lastPosition']['x'], f['_lastPosition']['y']], np.float32)
    previous = np.array([f['_secondLastPosition']['x'], f['_secondLastPosition']['y']], np.float32)
    initial = previous+(pos-previous)*(age/tick)
    correction = np.array([enemy['position']['x'], enemy['position']['y']])-initial
    output, rotations, steps = [], [], 0
    rotation = 0.
    for t in times:
        wanted = int(math.floor((age+t+1e-8)/tick))
        while steps < wanted:
            previous = pos.copy()
            pos, rotation = update(pos.copy(), tick)
            steps += 1
        alpha = np.clip((age+t-steps*tick)/tick, 0., 1.)
        output.append(previous+(pos-previous)*alpha+correction)
        rotations.append(rotation)
    return np.asarray(output), np.asarray(rotations)


def forecast(enemy, times, observation, player):
    """Return original root displacement/rotation, or a specific missing rule."""
    from arena_privileged_model import phase, xy
    f, c, kind = enemy['fields'], enemy['custom'], enemy['type']
    zero = np.zeros((len(times), 2))
    angles = np.zeros(len(times))
    source = kind+'.FixedUpdateMovement'
    if kind in ('EnemyPinball','EnemyBlowFish'):
        from arena_privileged_pinball import forecast as pinball
        return pinball(enemy,times,observation,player)
    if kind == 'EnemyHideBlade':
        mode = phase(f['_enemyState'])
        if not enemy.get('grown_colliders'):
            return None, 'hidden_blade_original_tween_target_missing'
        if mode not in ('none','movetoninja'):
            return None, 'hidden_blade_phase:'+mode
        until = max(0.,(enemy['position']['x']-player.initial.x-c['_activateDistance'])/max(.001,player.speed))
        age = max(0.,observation['state']['time']-f['_lastFixedUpdateTime'])
        activation = max(0.,math.ceil(until/player.tick)*player.tick-age) if mode=='none' else 0.
        # The original collider grows with its render-clock tween. Bounding
        # the complete authored target from activation is conservative and
        # cannot miss the disabled/zero-scale warning phase.
        return (zero,angles,'EnemyHideBlade.ProcessState/GrowingOut; original full tween target envelope',
                times>=activation),None
    if kind in ('EnemyBlade', 'EnemySpiderWeb'):
        # Blade's feedback rotation only starts after a trigger hit. Ordinary
        # living blades and webs have no autonomous movement in these sources.
        if kind == 'EnemyBlade' and f.get('_bCollider') and f.get('_triggerFeedbackRotate'):
            return None, 'blade_trigger_feedback_rotation'
        return (zero, angles, source), None
    if kind in ('EnemyDart','EnemyEliteDart'):
        # EliteDart overrides FixedUpdateMovement with StraightFly's method;
        # its separate gravity is exclusively the already-dead branch. Both
        # inherit Dart.Update/RotateUpdate at the rendering clock.
        mode = phase(f['_currState'])
        if mode not in ('none', 'fly'):
            return None, 'straight_fly_phase:'+mode
        velocity = xy(f['_velocity'])
        if mode == 'none':
            # Original StateUpdate changes to fly after crossing right+2;
            # movement is first applied on the following physical tick.
            edge = observation['camera']['right']['x']+2.
            enter = max(0., (enemy['position']['x']-edge)/max(.001, player.speed))
            delay = math.ceil(enter/player.tick)*player.tick+player.tick
        else:
            delay = 0.
        zero = np.maximum(0., times-delay)[:, None]*velocity
        # RotateUpdate runs at the render clock, independently of fly state.
        angles = np.deg2rad(c['_speedRotate'])*times
        return (zero, angles, 'EnemyStraightFly.StateUpdate + EnemyDart.RotateUpdate'), None
    if kind in ('EnemyCurveBat', 'EnemyGhostFire','EnemyFlyFairy'):
        if kind=='EnemyFlyFairy' and f['_needMove']:
            return None,'fairy_accelerated_entry_motion'
        mode = phase(f['_currState'])
        if mode not in ('none','flytoninja'):
            return None, 'curve_entry_phase:'+mode
        initial = f['_currRadian']
        elapsed=0.
        def update(pos, dt):
            nonlocal initial,mode,elapsed
            elapsed+=dt
            if mode=='none':
                if pos[0]<observation['camera']['position']['x']+player.speed*elapsed+12:
                    mode='flytoninja'
                return pos,0.
            initial = np.float32(initial+np.float32(c['_angularSpeed']*dt))
            pos[0] = np.float32(pos[0]+np.float32(c['_speedX']*dt))
            pos[1] = np.float32(f['_referenceY']+np.float32(c['_amplitude']*math.sin(initial)))
            return pos, 0.
        positions, angles = native_steps(enemy, times, observation, update)
        return (positions-xy(enemy['position']), angles, 'EnemyCurve.UpdateCureMove'), None
    if kind == 'EnemySuspend':
        mode = phase(f['_state']); vy = np.float32(f['_speedY']); waiting = np.float32(f['_stayTime'])
        if mode not in ('stay', 'move'):
            return None, 'suspend_phase:'+mode
        def update(pos, dt):
            nonlocal mode, vy, waiting
            if mode == 'stay':
                waiting = np.float32(waiting-np.float32(dt))
                if waiting <= 0:
                    mode = 'move'
            elif vy != 0:
                y = np.float32(pos[1]+np.float32(vy*dt))
                if y >= f['_maxY']:
                    if not f['_changeSpeedDirAcc']:
                        vy = -vy
                    else:
                        vy = np.float32(vy-np.float32(f['_changeSpeedDirAcc']*dt)); pos[1] = y
                elif y <= f['_minY']:
                    if not f['_changeSpeedDirAcc']:
                        vy = -vy
                    else:
                        vy = np.float32(vy+np.float32(f['_changeSpeedDirAcc']*dt)); pos[1] = y
                else:
                    pos[1] = y
            pos[0] = np.float32(pos[0]+np.float32(f['_speedX']*dt))
            return pos, 0.
        positions, angles = native_steps(enemy, times, observation, update)
        return (positions-xy(enemy['position']), angles, source), None
    if kind == 'EnemyMace':
        mode = phase(f['_enemyState'])
        if mode not in ('none','rotation'):
            return None, 'mace_entry_phase:'+mode
        enter=max(0.,(enemy['position']['x']-player.initial.x-c['_activateDistance'])/max(.001,player.speed)) if mode=='none' else 0.
        # Native NinjaController.GetNinjaSpeed(), not a fitted angular rate.
        angles = np.deg2rad(f['_speedRotate']*observation['state']['speed']*.125)*np.maximum(0.,times-enter)
        return (zero, angles, 'EnemyMace.ProcessState'), None
    if kind in ('EnemyHook','EnemyBambooThorn'):
        mode = phase(f['_enemyState'])
        if mode != 'rotation':
            return None, 'hook_entry_phase:'+mode
        if not enemy.get('rotation_samples'):
            return None,'native_pendulum_rotation_samples_missing'
        theta = np.float32(np.deg2rad(enemy['rotation_samples']['last']))
        previous = np.deg2rad(enemy['rotation_samples']['previous'])
        omega = np.float32(f['_currAngularSpeed']); start = math.radians(enemy['rotation_z'])
        age = max(0., observation['state']['time']-f['_lastFixedUpdateTime'])
        steps = 0
        for i, t in enumerate(times):
            wanted = int(math.floor((age+t+1e-8)/player.tick))
            while steps < wanted:
                previous=float(theta)
                omega = np.float32(omega-np.float32(f['_gravityAcc']*player.tick*math.sin(theta)))
                theta = np.float32(theta+np.float32(omega*player.tick)); steps += 1
            alpha=np.clip((age+t-steps*player.tick)/player.tick,0.,1.)
            difference=(float(theta)-previous+math.pi)%(2*math.pi)-math.pi
            blend=complex(1-alpha,0)+alpha*complex(math.cos(difference/2),math.sin(difference/2))
            angles[i] = previous+2*math.atan2(blend.imag,blend.real)-start
        return (zero, angles, kind+'.ProcessState'), None
    return None, 'motion_model_missing'
