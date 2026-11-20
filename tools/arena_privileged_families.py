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
    'EnemyBambooWater': 'native_authored_rise_tween_envelope',
    'EnemyPoleaxeWarrior': 'native_distance_triggered_spine_weapon',
    'EnemyFruitMuppet': 'native_collectible_banana_role_callback',
    'EnemySmallSword': 'native_wait_charge_and_flight_on_constant_ground_reference',
    'EnemyPiranha': 'native_water_wait_jump_swim_with_root_rotation_envelope',
}


def collectible_kind(enemy):
    """One source-verified fruit callback, never a global zero-attack rule.

    EnemyFruitBase.ProcessOnTriggerEnter marks this banana dead, asks the
    ninja to PlayAttackAnim, then schedules its original collection effects.
    The fixed-board config and live instances both have zero attack. Other
    identities or altered damage require their own semantics.
    """
    if (enemy['type']=='EnemyFruitMuppet' and enemy.get('attack')==0
            and enemy.get('info',{}).get('_enemyType')=='EnemyFruitBanana: 280'
            and enemy['fields'].get('_species')=='Fruit: 160031'):
        return 'banana'
    return None


def progression_marker(item):
    """Original task UI/counter triggers, with no immediate role movement.

    EndSpecialTask can subsequently spawn its normal reward chest/score.
    This classification does not certify the task goal or grant its reward.
    """
    expected={'ItemSpecialTaskStart':('ItemSpecialTaskStart: 43','special_task_start'),
              'ItemSpecialTaskEnd':('ItemSpecialTaskEnd: 44','special_task_end')}
    spec=expected.get(item['type'])
    if (spec and item.get('info',{}).get('_itemType')==spec[0]
            and item.get('custom',{}).get('_render')==0
            and item['fields'].get('_pickupRecycle') is True):
        return spec[1]
    return None


def curve_range(keys,lower=0.,upper=1.):
    """Exact extrema of exported unweighted cubic Hermite curve segments."""
    if len(keys)<2 or not all(str(k['weighted_mode']).lower().startswith('none:')for k in keys):
        raise ValueError('weighted_or_missing_curve')
    if not keys[0]['time']<=lower<=upper<=keys[-1]['time']:
        raise ValueError('curve_wrap_domain')
    values=[]
    for a,b in zip(keys,keys[1:]):
        dt=b['time']-a['time']
        if dt<=0:raise ValueError('curve_key_order')
        if b['time']<lower or a['time']>upper:continue
        v,w=a['value'],b['value'];m,n=a['out_tangent']*dt,b['in_tangent']*dt
        coefficients=[2*v-2*w+m+n,-3*v+3*w-2*m-n,m,v]
        if not all(math.isfinite(x)for x in coefficients):raise ValueError('nonfinite_curve_tangent')
        lo=max(0.,(lower-a['time'])/dt);hi=min(1.,(upper-a['time'])/dt)
        points=[lo,hi]
        A,B,C=3*coefficients[0],2*coefficients[1],coefficients[2]
        if abs(A)<1e-12:
            if abs(B)>1e-12:points.append(-C/B)
        else:
            discriminant=B*B-4*A*C
            if discriminant>=0:
                root=math.sqrt(discriminant);points.extend(((-B-root)/(2*A),(-B+root)/(2*A)))
        for t in points:
            if lo<=t<=hi:values.append(float(np.polyval(coefficients,t)))
    if not values:raise ValueError('empty_curve_domain')
    return min(values),max(values)


def water_envelopes(enemy):
    """Original translation tween, including every future curve extremum.

    The warning collider can be disabled/inactive. Pose its authored shape at
    both limits without mutating a Transform, and enclose the whole rise.
    Timing is deliberately conservative; the physics collider is unchanged.
    """
    import copy
    from arena_privileged_model import phase,rows,xy
    tween=enemy.get('position_tween')
    if not tween or tween.get('curve_truncated'):
        return None,'water_bamboo_original_tween_missing'
    if enemy['custom'].get('_render')!=0:
        return None,'water_bamboo_unverified_render_variant'
    fields=tween['fields']
    if tween['type']!='uTools.uTweenPosition' or fields.get('isRect') is not False:
        return None,'water_bamboo_nonlocal_position_tween'
    method=phase(fields['method'])
    try:method_value=int(str(fields['method']).rsplit(':',1)[1])
    except (ValueError,IndexError):return None,'water_bamboo_easing_enum_missing'
    if method_value!=0 and not (method_value==22 and method=='linear'):
        return None,'water_bamboo_easing:'+method
    try:
        bounds=curve_range(tween['curve'])
        # Original Sample applies its custom curve twice for method zero;
        # the native linear easing passes the factor to the curve only once.
        if method_value==0:bounds=curve_range(tween['curve'],*bounds)
    except (ValueError,KeyError) as error:
        return None,'water_bamboo_curve:'+str(error)
    velocity=enemy['fields'].get('currMoveVelocity')
    if velocity is None or any(abs(velocity[a])>1e-6 for a in ('x','y','z')):
        return None,'water_bamboo_moving_root'
    first={c['id']:c for c in rows(tween['from_colliders'])if c.get('damage_kind')}
    last={c['id']:c for c in rows(tween['to_colliders'])if c.get('damage_kind')}
    damage={c['id']for c in rows(enemy['colliders'])if c.get('damage_kind')}
    if not damage or damage!=first.keys() or damage!=last.keys():
        return None,'water_bamboo_unposed_damage_collider'
    output=[]
    for identity in sorted(damage):
        a,b=first[identity],last[identity]
        if a['type']!='BoxCollider' or b['type']!='BoxCollider' or not a.get('authored_pose') or not b.get('authored_pose'):
            return None,'water_bamboo_nonbox_authored_collider'
        if np.linalg.norm(xy(a['extents'])-xy(b['extents']))>1e-5:
            return None,'water_bamboo_changing_collider_extent'
        # Translation keeps the original orientation/extent fixed, including
        # authored 3D depth projection. AABB union is conservative for all f.
        start,end=xy(a['center']),xy(b['center']);delta=end-start
        centers=np.array([start+f*delta for f in bounds])
        lo=centers.min(axis=0)-xy(a['extents']);hi=centers.max(axis=0)+xy(a['extents'])
        row=copy.deepcopy(b);row.pop('quad',None);row['active']=row['enabled']=True
        row['center'].update(x=float((lo[0]+hi[0])/2),y=float((lo[1]+hi[1])/2))
        row['extents'].update(x=float((hi[0]-lo[0])/2),y=float((hi[1]-lo[1])/2))
        row['authored_translation_envelope']=True;output.append(row)
    return output,None


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


def small_sword(enemy,times,observation,player,trajectory_states):
    """ProcessState's player-relative pivot and separate back-charge phase.

    GetNinjaLastPos supplies the physical root X, GetGroundY the ground Y;
    neither is the airborne ninja's rendered position. Only a constant native
    reference is currently proved. Slopes, platforms and hidden appearance
    callbacks remain explicit boundaries, not guessed linear motion.
    """
    from arena_privileged_model import phase,rows,xy
    f=enemy['fields'];mode=phase(f['_enemyState'])
    if mode not in ('wait','shoot'):
        return None,'small_sword_phase:'+mode
    binding=enemy.get('sword',{})
    if not binding.get('breath_present') or binding.get('breath_affects_damage') is not False:
        return None,'small_sword_unverified_breath_transform'
    hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
    if len(hurt)!=1 or any(c['type']!='BoxCollider' or c.get('spine_follow')
            or c.get('damage_owner')!=enemy['id'] or not c['active'] or not c['enabled'] for c in hurt):
        return None,'small_sword_original_box_binding'
    role=observation['role']['fields'];tick=observation['state']['fixedDeltaTime']
    if not player.native_samples or abs(f['_lastFixedUpdateTime']-role['_lastFixedUpdateTime'])>.0002:
        return None,'small_sword_reference_clock'
    vx=player.initial.vx
    if abs(vx-player.speed)>.001 or trajectory_states is not None and any(abs(m.vx-vx)>.001 for m in trajectory_states):
        return None,'small_sword_player_speed_transition'
    pivot=xy(f['_pivotPos']).astype(np.float32)
    if abs(pivot[0]-role['_lastPosition']['x'])>.001:
        return None,'small_sword_reference_position'
    horizon=max(times,default=0.)
    left=role['_lastPosition']['x']-1;right=left+abs(vx)*(horizon+tick)+3
    reference=[s for s in player.surfaces if s.right>=left and s.left<=right]
    if (not reference or observation.get('platforms') or any(abs(s.slope)>1e-8
            or s.vx or s.vy or abs(s.y-pivot[1])>.0001 for s in reference)):
        return None,'small_sword_nonconstant_ground_reference'
    cursor=left
    for s in sorted(reference,key=lambda s:s.left):
        if s.left>cursor+.001:
            return None,'small_sword_ground_reference_gap'
        cursor=max(cursor,s.right)
    if cursor<right:
        return None,'small_sword_ground_reference_missing'
    local=xy(f['_localPos']).astype(np.float32)
    velocity=xy(f['_velocity']).astype(np.float32)
    if abs(f['_velocity']['z'])>1e-8 or abs(f['_localPos']['z'])>1e-8 or abs(f['_pivotPos']['z'])>1e-8:
        return None,'small_sword_spatial_reference'
    magnitude=float(np.linalg.norm(velocity))
    unit=velocity/np.float32(magnitude) if magnitude>1e-5 else np.zeros(2,np.float32)
    waiting=np.float32(f['_flyTime']);charge=np.float32(f['_chargeTime'])
    follow=f['_stayRefNinja']
    def update(pos,dt):
        nonlocal mode,local,pivot,waiting,charge
        dt=np.float32(dt)
        pivot[0]=np.float32(pivot[0]+np.float32(vx*dt))
        if mode=='wait':
            waiting=np.float32(waiting-dt)
            if not follow:local=np.asarray(pos-pivot,dtype=np.float32)
            if waiting<=0:
                mode='shoot';charge=np.float32(.5)
        elif charge>0:
            charge=np.float32(charge-dt)
            # Original charge retreats at one unit/s along velocity's unit
            # direction, not at the eventual projectile speed.
            local=np.asarray(local-unit*dt,dtype=np.float32)
        else:
            local=np.asarray(local+velocity*dt,dtype=np.float32)
        return np.asarray(pivot+local,dtype=np.float32),0.
    positions,angles=native_steps(enemy,times,observation,update)
    rounding=8*max(abs(float(np.spacing(np.float32(enemy['position'][a]))))for a in ('x','y'))
    return (positions-xy(enemy['position']),angles,
            'EnemySmallSword.ProcessState/ShootOut; native physical pivot, wait, unit-speed charge and relative flight',
            None,None,dict(position_padding=rounding)),None


def piranha_steps(enemy,times,observation,activation_tick=None):
    """Original float32 fixed steps; scale/enabled do not render-interpolate."""
    f=enemy['fields'];mode=int(f['_enemyState'].rsplit(':',1)[1]);initial=mode
    vx,vy,g=(np.float32(f[k])for k in ('_velocityJumpX','_velocityJumpY','_gravity'))
    stay=np.float32(f['_stayTime'])
    # Original names: _swimTimer is the configured interval; _swimTime is
    # its current countdown. Reversing them incorrectly starts another jump.
    swim=np.float32(f['_swimTime']);scale=np.float32(enemy['scale']['x'])
    enabled=next(c['enabled']for c in enemy['colliders']if c.get('damage_kind'));samples=[(enabled,float(scale),mode)];step=0
    def update(pos,dt):
        nonlocal mode,vx,vy,g,stay,swim,scale,enabled,step
        dt=np.float32(dt);step+=1
        if mode==0:
            pos[0]=np.float32(pos[0]-np.float32(np.float32(f['_velocityInWater'])*dt))
            if step==activation_tick:
                # The native zero-wait branch skips state 1 altogether.
                mode=1 if stay>0 else 2
        elif mode==1:
            stay=np.float32(stay-dt)
            if stay<=0:mode=2
            else:pos[0]=np.float32(pos[0]+np.float32(observation['state']['speed']*dt))
        elif mode==2:
            pos[1]=np.float32(pos[1]+np.float32(.3));mode=3
            if f['_validYBottom']<=f['_startPosY']<=f['_validYTop']:enabled=True
        elif mode==3:
            pos[0]=np.float32(pos[0]-np.float32(vx*dt))
            pos[1]=np.float32(pos[1]+np.float32(vy*dt))
            oldvy=vy;vy=np.float32(vy-np.float32(np.float32(g*dt)*np.float32(3.5)))
            if oldvy>0:
                if f['_changeScale']:
                    height=np.float32(np.float32(pos[1]-np.float32(f['_waterPlanePosY']))-np.float32(f['_startPosY']))
                    factor=min(np.float32(1),np.float32(height/np.float32(f['_height'])))
                    difference=np.float32(np.float32(f['_endScale'])-np.float32(f['_startScale']))
                    scale=np.float32(np.float32(f['_startScale'])+np.float32(factor*np.float32(difference*np.float32(.5))))
                if vy<=0:
                    vx=np.float32(f['_velocityFallX']);vy=-np.float32(f['_velocityFallY']);g=np.float32(f['_gravityFall'])
            else:
                if f['_changeScale']:
                    denominator=np.float32(np.float32(np.float32(f['_height'])+np.float32(f['_startPosY']))-np.float32(f['_endPosY']))
                    height=np.float32(np.float32(pos[1]-np.float32(f['_waterPlanePosY']))-np.float32(f['_endPosY']))
                    factor=min(np.float32(1),np.float32(height/denominator))
                    difference=np.float32(np.float32(f['_endScale'])-np.float32(f['_startScale']))
                    scale=np.float32(np.float32(f['_endScale'])+np.float32(factor*np.float32(difference*np.float32(-.5))))
                if pos[1]<=f['_waterPlanePosY']+f['_endPosY']:
                    enabled=False;swim=np.float32(f['_swimTimer'])
                    pos[1]=np.float32(pos[1]-np.float32(.3));mode=4
        elif mode==4:
            swim=np.float32(swim-dt);pos[0]=np.float32(pos[0]-np.float32(vx*dt))
            if swim<=0:vy=np.float32(enemy['custom']['_speedJumpY']);mode=2
        samples.append((enabled,float(scale),mode))
        return pos,0.
    positions,_=native_steps(enemy,times,observation,update)
    age=np.clip(observation['state']['time']-f['_lastFixedUpdateTime'],0,observation['state']['fixedDeltaTime'])
    steps=np.floor((age+times+1e-8)/observation['state']['fixedDeltaTime']).astype(int)
    return positions,np.asarray(samples)[steps],initial


def piranha(enemy,times,observation,player,trajectory_states=None):
    """Original water/jump cycles with complete root-rotation hurt envelope."""
    from arena_privileged_model import rows,xy
    f=enemy['fields'];mode=int(f['_enemyState'].rsplit(':',1)[1]);tick=player.tick
    if mode not in range(5):return None,'piranha_phase:'+str(mode)
    if observation.get('camera',{}).get('direction')!=1:return None,'piranha_original_run_direction'
    if enemy['custom'].get('_render')!=0 or not enemy.get('local_movement_parent_identity'):
        return None,'piranha_render_or_parent_space'
    numeric=('_velocityJumpX','_velocityJumpY','_velocityInWater','_velocityFallX','_velocityFallY','_gravity','_gravityFall',
             '_stayTime','_swimTime','_swimTimer','_startScale','_endScale','_height','_waterPlanePosY','_startPosY','_endPosY')
    if not all(math.isfinite(f[k])for k in numeric):return None,'piranha_nonfinite_native_parameters'
    hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
    if (len(hurt)!=1 or hurt[0]['type']!='BoxCollider' or hurt[0].get('damage_kind')!='enemy_tag' or hurt[0].get('tag')!='Enemy'
            or hurt[0].get('damage_owner') not in (None,enemy['id']) or not hurt[0]['active']
            or hurt[0].get('rotation_envelope',{}).get('depth')!=0):
        return None,'piranha_original_root_box'
    if (max(abs(enemy['scale'][a]-enemy['scale']['x'])for a in ('x','y','z'))>1e-6
            or enemy['scale']['x']<0 or f['_startScale']<0 or f['_endScale']<0
            or f['_changeScale'] and (f['_height']<=0 or f['_height']+f['_startPosY']-f['_endPosY']<=0)):
        return None,'piranha_native_scale_domain'
    age=observation['state']['time']-f['_lastFixedUpdateTime']
    if not -.0002<=age<=tick+.0002:return None,'piranha_original_fixed_clock'
    age=np.clip(age,0,tick)
    count=int(math.floor((age+times[-1]+1e-8)/tick))
    activation=[None]
    if mode in (0,1):
        # Unknown item contacts are stopped by the controller's global domain
        # check. The family forecast remains conditional on no such contact,
        # so passive calibration can still compare known actor kinematics.
        if any(not name.startswith('item:') for name in player.unsupported):
            return None,'piranha_player_reference_unsupported'
        if trajectory_states is None:
            _,trajectory_states,valid=player.trajectory(times)
            if not valid:return None,'piranha_player_reference_unsupported'
        if any(abs(m.vx-observation['state']['speed'])>.001 for m in trajectory_states):
            return None,'piranha_player_speed_transition'
    if mode==0:
        role=observation['role']['fields']
        actual=role.get('_lastRoleObjPos')
        if actual is None or abs(actual['x']-player.initial.physical_x-player.initial.offset_render)>.025:
            return None,'piranha_original_role_reference'
        query=np.maximum(0.,np.arange(1,count+1)*tick-age)
        xs=np.array([m.physical_x+m.offset_render for m in trajectory_states])
        old=np.array([m.previous_x+m.offset_render for m in trajectory_states])
        lower=np.interp(query,times,np.minimum(xs,old))-.025
        upper=np.interp(query,times,np.maximum(xs,old))+.025
        # A carrier/ground transition can leave a residual RoleObj offset.
        # Enclose both holding that original offset and its predicted settling;
        # do not treat an immediately settled parent as an exact native fact.
        residual=actual['x']-player.initial.physical_x
        physical=np.array([m.physical_x for m in trajectory_states])
        previous=np.array([m.previous_x for m in trajectory_states])
        lower=np.minimum(lower,np.interp(query,times,np.minimum(physical,previous))+min(0.,residual)-.025)
        upper=np.maximum(upper,np.interp(query,times,np.maximum(physical,previous))+max(0.,residual)+.025)
        # Enumerate every feasible *activation tick*, not key combinations.
        # Both native callback orders and the sampled actor reference are
        # enclosed, including intermediate ticks around the jump apex.
        px=np.float32(f['_lastPosition']['x']);possible=certain=None
        for k in range(1,count+1):
            px=np.float32(px-np.float32(f['_velocityInWater']*tick))
            if possible is None and px<upper[k-1]+f['_activeBeginDistance']:possible=k
            if px<lower[k-1]+f['_activeBeginDistance']:certain=k;break
        if possible is not None:
            if (certain or count)-possible>8:return None,'piranha_activation_uncertainty'
            activation=list(range(possible,(certain or count)+1))
            if certain is None:activation.append(None)
    branches=[piranha_steps(enemy,times,observation,a)for a in activation]
    positions=np.array([r[0]for r in branches]);states=np.array([r[1]for r in branches])
    # CurrGroundY changes when a fish crosses a terrain seam. Accept only a
    # proved constant original ground over every possible future root X.
    margin=1+2*tick*max(abs(f['_velocityJumpX']),abs(f['_velocityFallX']),observation['state']['speed'])
    left=float(positions[:,:,0].min()-margin);right=float(positions[:,:,0].max()+margin)
    support=enemy.get('native_support',{})
    a,b=support.get('start',{}),support.get('finish',{})
    contained=(support.get('is_ground') or support.get('is_line')) and a.get('x',math.inf)<=left and b.get('x',-math.inf)>=right
    if not contained or abs(a['y']-f['_waterPlanePosY'])>1e-5 or abs(b['y']-a['y'])>1e-8:
        return None,'piranha_ground_reference_crossing'
    centers=(positions.min(axis=0)+positions.max(axis=0))/2
    spread=np.linalg.norm(positions-centers,axis=2).max(axis=0)
    scale=states[:,:,1].max(axis=0)
    if not np.isfinite(scale).all() or np.any(scale<0):return None,'piranha_predicted_scale_domain'
    active=states[:,:,0].any(axis=0)
    radius=hurt[0]['rotation_envelope']['root_radius']*scale+spread
    rounding=max(.00001,8*max(abs(float(np.spacing(np.float32(enemy['position'][a]))))for a in ('x','y')))
    return (centers-xy(enemy['position']),np.zeros(len(times)),
            'EnemyPiranha.FixedUpdateMovement/ChangeFishState; native activation/wait/jump/swim, collider state and full root-rotation envelope',
            active,radius,dict(position_padding=rounding,activation_ticks=activation)),None


def forecast(enemy, times, observation, player, trajectory_states=None):
    """Return original root displacement/rotation, or a specific missing rule."""
    from arena_privileged_model import phase, xy
    f, c, kind = enemy['fields'], enemy['custom'], enemy['type']
    zero = np.zeros((len(times), 2))
    angles = np.zeros(len(times))
    source = kind+'.FixedUpdateMovement'
    if kind=='EnemyPiranha':
        return piranha(enemy,times,observation,player,trajectory_states)
    if kind=='EnemySmallSword':
        return small_sword(enemy,times,observation,player,trajectory_states)
    if kind=='EnemyPoleaxeWarrior':
        from arena_privileged_poleaxe import forecast as poleaxe
        return poleaxe(enemy,times,observation,player,trajectory_states)
    if kind=='EnemyBambooWater':
        mode=phase(f['_enemyState'])
        if mode not in ('none','movetoninja'):
            return None,'water_bamboo_phase:'+mode
        bounds,reason=water_envelopes(enemy)
        if bounds is None:return None,reason
        return (zero,angles,'EnemyBambooWater.ProcessState/uTweenPosition.Sample; original full-rise envelope',
                np.ones(len(times),bool),bounds),None
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
