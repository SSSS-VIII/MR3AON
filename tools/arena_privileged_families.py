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
    'EnemyArrow': 'native_untracked_ballistic_arrow_and_soil_envelope',
    'EnemyKill': 'stationary_original_shape_before_contact_recycle',
    'EnemyStraightBack': 'native_go_brake_follow_and_return_centered_sphere',
    'EnemyFruitPinball': 'native_free_pinball_with_rotating_authored_collider_envelope',
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


def forecast(enemy, times, observation, player, trajectory_states=None):
    """Return original root displacement/rotation, or a specific missing rule."""
    from arena_privileged_model import phase, xy
    f, c, kind = enemy['fields'], enemy['custom'], enemy['type']
    zero = np.zeros((len(times), 2))
    angles = np.zeros(len(times))
    source = kind+'.FixedUpdateMovement'
    if kind in ('EnemyPinball','EnemyBlowFish','EnemyFruitPinball'):
        if kind=='EnemyFruitPinball':
            if not enemy.get('local_movement_parent_identity'):
                return None,'fruit_pinball_local_movement_parent_not_identity'
            if any(not c.get('rotation_envelope') for c in enemy['colliders'] if c.get('damage_kind')):
                return None,'fruit_pinball_authored_rotation_envelope_missing'
        from arena_privileged_pinball import forecast as pinball
        return pinball(enemy,times,observation,player)
    if kind=='EnemyStraightBack':
        # The original visual child rotates, but the authored hurt collider is
        # a sphere centered on the root. Other shapes need a separate model.
        hurt=[c for c in enemy['colliders'] if c.get('damage_kind')]
        if not hurt or any(c['type']!='SphereCollider' or
                np.linalg.norm(xy(c['center'])-xy(enemy['position']))>.001 for c in hurt):
            return None,'return_dart_requires_original_centered_sphere'
        mode=int(f['_enemyState'].rsplit(':',1)[1]);initial_mode=mode
        if mode not in range(6):return None,'return_dart_phase:'+str(mode)
        if mode in (0,1) and (abs(player.initial.vx-player.speed)>.1 or
                trajectory_states is not None and any(abs(m.vx-player.speed)>.1 for m in trajectory_states)):
            return None,'return_dart_native_player_speed_transition'
        vx=np.float32(f['_velocity']);stay=np.float32(f['_stayTime']);elapsed=0.
        tick=observation['state']['fixedDeltaTime']
        age=max(0.,observation['state']['time']-f['_lastFixedUpdateTime'])
        role_x=observation['role']['fields']['_lastPosition']['x']
        right=observation['camera']['right']['x']
        def update(pos,dt):
            nonlocal mode,vx,stay,elapsed
            elapsed+=dt
            if mode==0:
                render=max(0.,(math.ceil((elapsed-age)*60-1e-6)-1)/60)
                if pos[0]<right+player.speed*render+2:mode=1
            elif mode==1:
                pos[0]=np.float32(pos[0]-np.float32(vx*dt))
                if pos[0]<=role_x+player.speed*elapsed+f['_stayOffSetX']+f['_stopDistance']:mode=2
            elif mode==2:
                vx=np.float32(vx-np.float32(f['_accelerate']*dt))
                pos[0]=np.float32(pos[0]-np.float32(vx*dt))
                if vx<=0:mode=3
            elif mode==3:
                pos[0]=np.float32(pos[0]+np.float32(player.speed*dt))
                stay=np.float32(stay-np.float32(dt))
                if stay<=0:mode=4
            elif mode in (4,5):
                if mode==4:vx=np.float32(f['_backSpeed'])
                pos[0]=np.float32(pos[0]+np.float32(np.float32(player.speed+vx)*np.float32(dt)))
                mode=5
            return pos,0.
        positions,angles=native_steps(enemy,times,observation,update)
        prediction=(positions-xy(enemy['position']),angles,
                    'EnemyStraightBack.FixedUpdateMovement; original centered SphereCollider')
        if initial_mode==0:
            # As with the pendulum, camera activation spans fixed/render
            # clocks. Keep this uncertainty in planning geometry, separate
            # from the nominal point prediction and native route validation.
            radius=math.ceil((tick+1/60)/tick)*tick
            speed=max(abs(f['_velocity']),abs(player.speed+f['_backSpeed']),abs(player.speed))
            prediction+= (None,None,dict(position_padding=2*radius*speed))
        return prediction,None
    if kind=='EnemyArrow':
        mode=int(f['_enemyState'].rsplit(':',1)[1])
        if mode==4:
            # The enum can already be onGround while BaseObject is still
            # interpolating its final impact tick. Preserve the root settling.
            positions,_=native_steps(enemy,times,observation,lambda pos,dt:(pos,0.))
            return (positions-xy(enemy['position']),angles,
                    'EnemyArrow.StateLogic; native embedded collider settling'),None
        if mode not in (0,1,2,3):
            return None,'arrow_phase:'+str(mode)
        if f['_isAimNinjaX']:
            return None,'arrow_native_aim_tween'
        if int(f['_arrowType'].rsplit(':',1)[1])==2:
            return None,'arrow_behind_player_relocation'
        vx,vy=np.float32(f['_velocityX']),np.float32(f['_velocityY'])
        waiting=np.float32(f['_stayTime']);rotation=math.radians(enemy['rotation_z']);start=rotation
        elapsed=0.
        def update(pos,dt):
            nonlocal mode,vx,vy,waiting,rotation,elapsed
            elapsed+=dt
            if mode==1:
                if pos[0]<player.initial.x+player.speed*elapsed+f['_activeDistance']:
                    mode=2
            elif mode==2:
                waiting=np.float32(waiting-np.float32(dt))
                if waiting<0:mode=3
            elif mode==3:
                # StateLogic first moves using the old velocities, then
                # changes gravity/acceleration and aligns the arrow to them.
                pos[0]=np.float32(pos[0]-np.float32(vx*dt))
                pos[1]=np.float32(pos[1]+np.float32(vy*dt))
                vy=np.float32(vy-np.float32(np.float32(f['_gravity']*dt)*np.float32(3.5)))
                vx=np.float32(vx+np.float32(np.float32(f['_velocityAccX']*dt)*np.float32(3.5)))
                if vx==0:vx=np.float32(.001)  # native float at 0x11b24f4
                theta=math.atan2(vy,vx)+f['_rotateZRandom'];rotation=-theta
                tip=pos[1]-f['_deepInGround']*abs(math.sin(theta))
                if tip<=f['_currGroundY']:
                    pos[1]=np.float32(f['_currGroundY']+f['_deepInGround']*abs(math.sin(theta)));mode=4
            return pos,(rotation-start+math.pi)%(2*math.pi)-math.pi
        positions,angles=native_steps(enemy,times,observation,update)
        # UpdateCollider clips the embedded portion of the original box.
        # Its complete untrimmed box encloses that future subset. Never grow
        # an already-clipped box back by guessing its mesh dimensions.
        if not enemy.get('untrimmed_colliders') and any(
                c.get('damage_kind') and c['scale']['x']!=enemy['scale']['x']
                for c in enemy['colliders']):
            return None,'arrow_partially_clipped_flight_shape'
        return (positions-xy(enemy['position']),angles,
                'EnemyArrow.StateLogic/ShootIntoGround; untrimmed soil envelope'),None
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
    if kind in ('EnemyBlade', 'EnemySpiderWeb','EnemyKill'):
        # Blade's feedback rotation only starts after a trigger hit. Ordinary
        # living blades and webs have no autonomous movement in these sources.
        if kind == 'EnemyBlade' and f.get('_bCollider') and f.get('_triggerFeedbackRotate'):
            return None, 'blade_trigger_feedback_rotation'
        return (zero, angles, 'EnemyBase.FixedUpdateMovement; original stationary shape' if kind=='EnemyKill' else source), None
    if kind in ('EnemyDart','EnemyEliteDart'):
        # EliteDart overrides FixedUpdateMovement with StraightFly's method;
        # its separate gravity is exclusively the already-dead branch. Both
        # inherit Dart.Update/RotateUpdate at the rendering clock.
        mode = phase(f['_currState'])
        if mode not in ('none', 'fly'):
            return None, 'straight_fly_phase:'+mode
        velocity = xy(f['_velocity'])
        elapsed=0.
        def update(pos,dt):
            nonlocal mode,elapsed
            elapsed+=dt
            if mode=='none':
                # EnterScreen changes the phase only. In particular the first
                # fly observation can have equal physical position samples;
                # root+t*velocity would skip that original interpolation lag.
                if pos[0]<observation['camera']['right']['x']+2.+player.speed*elapsed:
                    mode='fly'
                return pos,0.
            return np.asarray(pos+np.float32(dt)*velocity,dtype=np.float32),0.
        positions,_=native_steps(enemy,times,observation,update)
        zero=positions-xy(enemy['position'])
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
        waiting_entry=mode=='none'
        if mode not in ('none','rotation'):
            return None, 'hook_entry_phase:'+mode
        if not enemy.get('rotation_samples'):
            return None,'native_pendulum_rotation_samples_missing'
        theta = np.float32(np.deg2rad(enemy['rotation_samples']['last']))
        previous = np.deg2rad(enemy['rotation_samples']['previous'])
        omega = np.float32(f['_currAngularSpeed']); start = math.radians(enemy['rotation_z'])
        maximum_speed=abs(float(omega))
        age = max(0., observation['state']['time']-f['_lastFixedUpdateTime'])
        steps = 0
        for i, t in enumerate(times):
            wanted = int(math.floor((age+t+1e-8)/player.tick))
            while steps < wanted:
                previous=float(theta)
                steps+=1
                if mode=='none':
                    # Hook's waiting branch switches to rotation at the
                    # original camera edge + 2; it does not integrate that
                    # activation tick. BambooThorn uses the same dispatch.
                    elapsed=steps*player.tick-age
                    # FixedUpdate reads the camera cached by the preceding
                    # 60 Hz render frame, before this frame's LateUpdate. A
                    # continuous camera here can start the pendulum one full
                    # native tick early even with the correct physics age.
                    elapsed=max(0.,(math.ceil(elapsed*60-1e-6)-1)/60)
                    if enemy['position']['x']<observation['camera']['right']['x']+2+player.speed*elapsed:
                        mode='rotation'
                else:
                    omega = np.float32(omega-np.float32(f['_gravityAcc']*player.tick*math.sin(theta)))
                    theta = np.float32(theta+np.float32(omega*player.tick))
                    maximum_speed=max(maximum_speed,abs(float(omega)))
            alpha=np.clip((age+t-steps*player.tick)/player.tick,0.,1.)
            difference=(float(theta)-previous+math.pi)%(2*math.pi)-math.pi
            blend=complex(1-alpha,0)+alpha*complex(math.cos(difference/2),math.sin(difference/2))
            angles[i] = previous+2*math.atan2(blend.imag,blend.real)-start
        if waiting_entry:
            # Camera cached position can straddle a render and physics update.
            # Do not claim a point-perfect future activation clock: enclose all
            # adjacent native activation ticks using an angular speed bound.
            # Once the actual phase is rotation, the exact native clock above
            # applies and this additional envelope disappears.
            radius=math.ceil((player.tick+1/60)/player.tick)*player.tick
            angular_bound=radius*(maximum_speed+abs(f['_gravityAcc'])*(radius+player.tick))
            return (zero,angles,kind+'.ProcessState; native camera-cache activation envelope',
                    None,None,dict(angular_padding=angular_bound,activation_uncertainty_seconds=radius)),None
        return (zero, angles, kind+'.ProcessState'), None
    return None, 'motion_model_missing'
