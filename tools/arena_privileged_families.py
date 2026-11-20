"""Additional source-derived native motion families, independent of vision.

Registration is a modelling claim, never an acceptance result. Every reducer
requires its actual instance fields; unimplemented variants remain explicit.
"""
import math
from functools import lru_cache
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
    'EnemyRollingBase': 'native_activation_fall_slope_projection_wall_and_pit_chain',
    'EnemyRockTiger': 'native_distance_aim_extend_retract_head_capsule_envelope',
    'EnemySuspendSpecial': 'native_enabled_connected_ball_hover',
    'EnemyConnectElectricBall': 'native_pulsed_link_between_moving_endpoints',
    'EnemyRotateElectricBall': 'native_rigid_rotating_electric_assembly',
    'EnemyBullutFireRobot': 'native_accelerating_camera_relative_fire_bullet',
    'EnemyBullutLaser': 'native_camera_relative_bullet_with_authored_growth_envelope',
    'EnemyAlarmShooter': 'native_camera_relative_body_and_complete_pending_laser_queue',
    'EnemyBrambles': 'native_lift_stab_and_bounded_warning_callback',
    'EnemyBramblesSingleThorn': 'native_parent_lift_stab_generated_thorn',
    'EnemyBrambleCollider': 'native_parent_lift_stab_movement_contact_avoidance',
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


def role_reference_bounds(times,motors,query,actual):
    """Enclose cached physical roots at fixed ticks between render samples.

    Physical samples are step functions. Interpolating them can postpone a
    distance trigger by a whole tick. Use both neighboring observations and
    the previous/current root instead; retain the observed parent offset as
    well as its predicted settling.
    """
    physical=np.array([m.physical_x for m in motors]);previous=np.array([m.previous_x for m in motors])
    offsets=np.array([m.offset_render for m in motors]);residual=actual['x']-physical[0]
    lo=np.clip(np.searchsorted(times,query,side='right')-1,0,len(times)-1)
    hi=np.clip(np.searchsorted(times,query,side='left'),0,len(times)-1)
    lower=np.minimum(physical,previous)+np.minimum(offsets,min(0.,residual))
    upper=np.maximum(physical,previous)+np.maximum(offsets,max(0.,residual))
    return np.minimum(lower[lo],lower[hi])-.025,np.maximum(upper[lo],upper[hi])+.025


def camera_x_bounds(observation,times,player,trajectory_states=None):
    """Source default camera X damping, including physical update ordering.

    GetReferencePivotPos used by native bullets returns the camera's cached
    physical position. It is neither the rendered ninja nor a fixed offset
    moving forever at the current speed. Enclose both actor samples at each
    source Lerp and both speed samples that can feed its gain.
    """
    from arena_privileged_model import phase
    try:
        f=observation['camera']['fields'];role=observation['role']['fields']
        if (f['_cameraMode']!=0 or any(f[k]for k in ('<StopFollowNinja>k__BackingField',
                '_gameEndSlowDown','_cameraShift','_cameraRotate','_focusing','_ctrlAnimEnable'))or
                role['_runStopped']or role['<RunStopSlowEnd>k__BackingField']or
                role['_getStuck']or role['<StuckEndRecover>k__BackingField']or
                phase(observation['state']['state'])!='game'):
            raise ValueError('camera_x_unverified_control_branch')
        tick=player.tick;age=observation['state']['time']-f['_lastFixedUpdateTime']
        if not -.0002<=age<=tick+.0002:raise ValueError('camera_x_original_fixed_clock')
        if abs(f['_cameraSupportSpeedRe'])>1e-5:raise ValueError('camera_x_support_relative_speed')
        if trajectory_states is None:
            _,trajectory_states,valid=player.trajectory(times)
            if not valid:raise ValueError('camera_x_unsupported_actor_path')
        count=int(math.floor((max(0.,age)+times[-1]+1e-8)/tick))
        query=np.maximum(0.,np.arange(1,count+1)*tick-max(0.,age))
        low,high=role_reference_bounds(times,trajectory_states,query,observation['state']['position'])
        lower=[f['_lastPosition']['x']];upper=lower.copy()
        offset=f['_cameraOffset']['x']
        offsets={(phase(f['_cameraOffsetType']),offset)}
        if not all(math.isfinite(v)for v in (lower[0],offset)):raise ValueError('camera_x_nonfinite_native_parameter')
        vx=np.array([m.vx for m in trajectory_states])
        for i,t in enumerate(query):
            a=max(0,int(np.searchsorted(times,t,side='right'))-1);b=min(len(times)-1,int(np.searchsorted(times,t,side='left')))
            previous=max(0,int(np.searchsorted(times,max(0.,t-tick),side='right'))-1)
            branches=set()
            for mode in {trajectory_states[k].mode for k in (previous,a,b)}:
                # Original UpdateNinjaPhysicsState only handles 1/4 (line)
                # and 2/3 (line transfers). Ground/jump do not restore a
                # carrier-modified offset. ChangeCameraOffset also returns
                # early if the offset *type* has not changed.
                target='online'if mode in ('runonline','runonlinedown')else 'onlinedown'if mode in ('rolltolineon','rolltolinedown')else None
                for current,x in offsets:
                    name='_cameraOffset_line'if target=='online'else '_cameraOffset_lineDown'
                    branches.add((target,f[name]['x'])if target is not None and target!=current else(current,x))
            offsets=branches
            gains=[min(1.,max(0.,(abs(v)+4.)/6.*tick))for v in (vx[a],vx[b])]
            candidates=[np.float32(np.float32(x)+np.float32(np.float32(target-x)*np.float32(g)))
                        for x in (lower[-1],upper[-1])for offset in {v for _,v in offsets}
                        for target in (low[i]+offset,high[i]+offset)for g in gains]
            lower.append(float(min(candidates)));upper.append(float(max(candidates)))
        return (np.asarray(lower),np.asarray(upper)),None
    except (KeyError,ValueError)as error:return None,str(error)


def laser_growth_bounds(enemy,collider):
    """Joint scale/translation envelope, including both curve overshoots."""
    from arena_privileged_model import rows,xy
    bindings=[]
    for tween in rows(enemy['laser_growth']['scales']):
        first=next((c for c in rows(tween['from_colliders'])if c['id']==collider['id']),None)
        last=next((c for c in rows(tween['to_colliders'])if c['id']==collider['id']),None)
        if first is None and last is None:continue
        if (first is None or last is None or not first.get('quad')or not last.get('quad')or
                first.get('depth_tilt')or last.get('depth_tilt')or tween.get('curve_truncated')):
            raise ValueError('laser_growth_original_posed_box')
        method=int(str(tween['fields']['method']).rsplit(':',1)[1])
        if method not in (0,22):raise ValueError('laser_growth_unverified_easing')
        limits=curve_range(tween['curve'])
        if method==0:limits=curve_range(tween['curve'],*limits)
        a=np.array([xy(p)for p in first['quad']]);b=np.array([xy(p)for p in last['quad']])
        points=np.concatenate([a+(b-a)*factor for factor in limits])
        bindings.append((tween['root'],points))
    if not bindings or len({root for root,_ in bindings})!=1:
        raise ValueError('laser_growth_missing_or_nested_scale_binding')
    points=np.concatenate([np.array([xy(p)for p in collider['quad']]),*[p for _,p in bindings]])
    translations=[]
    for tween in rows(enemy['laser_growth']['positions']):
        first=next((c for c in rows(tween['from_colliders'])if c['id']==collider['id']),None)
        last=next((c for c in rows(tween['to_colliders'])if c['id']==collider['id']),None)
        if first is None and last is None:continue
        if (not first or not last or tween['root']!=bindings[0][0]or tween.get('curve_truncated')or
                tween['fields'].get('isRect')is not False or
                first.get('depth_tilt')or last.get('depth_tilt')):
            raise ValueError('laser_growth_unverified_translation_binding')
        method=int(str(tween['fields']['method']).rsplit(':',1)[1])
        if method not in (0,22):raise ValueError('laser_growth_unverified_translation_easing')
        limits=curve_range(tween['curve'])
        if method==0:limits=curve_range(tween['curve'],*limits)
        a=xy(first['center'])-xy(collider['center']);b=xy(last['center'])-xy(collider['center'])
        translations.extend(a+(b-a)*factor for factor in limits)
    if not translations:raise ValueError('laser_growth_original_translation_missing')
    points=np.concatenate([points+delta for delta in [np.zeros(2),*translations]])
    lo,hi=points.min(axis=0),points.max(axis=0)
    return (lo+hi)/2,(hi-lo)/2


def camera_relative_bullet(enemy,times,observation,player,trajectory_states=None,reference=None):
    """Original accelerated BulletMoveLogic with the real camera reference.

    Local X moves relative to GetReferencePivotPos; Y integrates directly in
    world space. The FireRobot subclass only recycles below a native ground
    surface and creates a visual effect. Keeping its flying geometry alive
    past that removal is conservative, not a prediction of a second attack.
    """
    from arena_privileged_model import rows,xy
    try:
        f=enemy['fields'];binding=enemy['bullet_geometry'];kind=enemy['type']
        if kind not in ('EnemyBullutFireRobot','EnemyBullutLaser'):
            raise ValueError('camera_bullet_unverified_concrete_class')
        if not binding['parent_axes_identity']or f['_bullutType']!=0:
            raise ValueError('fire_bullet_unverified_parent_or_bullet_type')
        hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
        if (len(hurt)!=1 or hurt[0]['type']!='BoxCollider'or not hurt[0].get('quad')or
                hurt[0].get('depth_tilt')or not hurt[0]['active']or not hurt[0]['enabled']or
                hurt[0].get('damage_kind')!='enemy_callback'or hurt[0].get('damage_owner')!=enemy['id']):
            raise ValueError('fire_bullet_original_damage_box')
        c=hurt[0];chain=next((r for r in rows(binding['chains'])if r['id']==c['id']),{})
        whitelist={'UnityEngine.Transform','UnityEngine.BoxCollider','UnityEngine.MeshFilter',
                   'UnityEngine.MeshRenderer','UnityEngine.ParticleSystem','UnityEngine.ParticleSystemRenderer',
                   'UnityEngine.Rigidbody',kind,'EnemyBaseCollider'}
        if kind=='EnemyBullutLaser':
            # These original components affect alpha or the authored scale
            # bounded below. Any additional transform animation is rejected.
            whitelist|={'uTools.uTweenAlpha','uTools.uTweenScale','uTools.uTweenPosition','uTweenController'}
        if (not chain.get('complete')or not chain.get('includes_native_components')or
                any(name not in whitelist for node in rows(chain['nodes'])for name in rows(node['scripts']))):
            raise ValueError('fire_bullet_unverified_damage_transform_chain')
        for node in rows(chain['nodes']):
            if 'UnityEngine.Rigidbody'in rows(node['scripts'])and not node.get('rigidbody',{}).get('kinematic'):
                raise ValueError('fire_bullet_unverified_dynamic_rigidbody')
        numbers=[f['_bullutSpeed'],f['_speedAcc']]+[f[k][a]for k in ('_moveDir','_localPos','_pivotPos','_lastPosition','_secondLastPosition')for a in ('x','y','z')]
        if not all(math.isfinite(v)for v in numbers)or any(abs(f[k]['z'])>1e-6 for k in ('_moveDir','_localPos','_pivotPos')):
            raise ValueError('fire_bullet_nonplanar_or_nonfinite_parameters')
        tick=player.tick;age=observation['state']['time']-f['_lastFixedUpdateTime']
        cf=observation['camera']['fields']
        if not -.0002<=age<=tick+.0002 or abs(f['_lastFixedUpdateTime']-cf['_lastFixedUpdateTime'])>.0002:
            raise ValueError('fire_bullet_original_reference_clock')
        numeric=8*max(abs(float(np.spacing(np.float32(v))))for v in numbers)+.0001
        if abs(f['_lastPosition']['x']-np.float32(f['_pivotPos']['x']+f['_localPos']['x']))>numeric:
            raise ValueError('fire_bullet_original_local_reference')
        cam,reason=reference if reference is not None else camera_x_bounds(observation,times,player,trajectory_states)
        if cam is None:return None,reason
        camera_low,camera_high=cam
        pivot=f['_pivotPos']['x'];known=[cf[k]['x']for k in ('_lastPosition','_secondLastPosition')]
        if not min(known)-numeric<=pivot<=max(known)+numeric:
            raise ValueError('fire_bullet_unknown_reference_override')
        age=np.clip(age,0.,tick);steps=np.floor((age+np.asarray(times)+1e-8)/tick).astype(int)
        speed=np.float32(f['_bullutSpeed']);acc=np.float32(f['_speedAcc']);direction=xy(f['_moveDir']).astype(np.float32)
        local_x=np.float32(f['_localPos']['x']);y=np.float32(f['_lastPosition']['y'])
        low=[xy(f['_lastPosition'])];high=[low[0].copy()]
        for k in range(1,int(steps[-1])+1):
            speed=np.float32(speed+np.float32(acc*np.float32(tick)))
            local_x=np.float32(local_x+np.float32(direction[0]*np.float32(np.float32(tick)*speed)))
            y=np.float32(y+np.float32(np.float32(direction[1]*np.float32(tick))*speed))
            low.append(np.array([np.float32(min(camera_low[k-1],camera_low[k])+local_x),y]))
            high.append(np.array([np.float32(max(camera_high[k-1],camera_high[k])+local_x),y]))
        previous=xy(f['_secondLastPosition']);physical=xy(f['_lastPosition'])
        correction=xy(enemy['position'])-(previous+(physical-previous)*(age/tick))
        prev_low=np.asarray([previous,*low[:-1]]);prev_high=np.asarray([previous,*high[:-1]])
        alpha=np.clip((age+np.asarray(times)-steps*tick)/tick,0.,1.)[:,None]
        lo=prev_low[steps]*(1-alpha)+np.asarray(low)[steps]*alpha+correction
        hi=prev_high[steps]*(1-alpha)+np.asarray(high)[steps]*alpha+correction
        center,extent=laser_growth_bounds(enemy,c)if kind=='EnemyBullutLaser'else(xy(c['center']),xy(c['extents']))
        offset=center-xy(enemy['position'])
        numeric+=2*abs(float(np.spacing(np.float32(observation['state']['time']))))*(abs(float(speed))+abs(player.speed))
        geometry={c['id']:((lo+hi)/2+offset,(hi-lo)/2+extent+numeric)}
        zero=np.zeros((len(times),2))
        return (zero,np.zeros(len(times)),
                'EnemyBullut.BulletMoveLogic; native accelerated camera-relative X/world Y'+
                    ('; original laser scale-curve envelope'if kind=='EnemyBullutLaser'else'; conservative FireRobot ground-recycle lifetime'),
                np.ones(len(times),bool),geometry),None
    except (KeyError,ValueError)as error:return None,str(error)


def alarm_shooter_path(enemy,times,observation,player,trajectory_states=None,reference=None):
    """Source MoveIn/Attack/Leave clocks and the complete pending shot list."""
    from arena_privileged_model import phase,rows,xy
    try:
        f=enemy['fields'];binding=enemy['alarm_shooter'];bullets=rows(binding['bullets'])
        if binding.get('truncated')or f['_bulletIndex']not in range(len(bullets)+1):
            raise ValueError('alarm_shooter_complete_pending_bullets')
        mode=phase(f['_state']);direction=f['_moveDirNum'];tick=player.tick
        if mode not in ('movein','attack','leave')or direction not in (-1,1):
            raise ValueError('alarm_shooter_native_phase_or_direction')
        if not enemy['bullet_geometry']['parent_axes_identity']or abs(enemy['rotation_z'])>1e-5:
            raise ValueError('alarm_shooter_original_planar_parent')
        names=('_delayTime','_shootMoveSpeed','_shootMoveOutSpeed','_shootLeaveSpeed','_shootInteralTime',
               '_shootTimer','_beforeShootTime','_afterShootTime')
        if not all(math.isfinite(f[k])for k in names)or not all(math.isfinite(f[k][a])for k in
                ('_localPos','_targetPos','_lastPosition','_secondLastPosition')for a in ('x','y','z')):
            raise ValueError('alarm_shooter_native_parameter_domain')
        age=observation['state']['time']-f['_lastFixedUpdateTime'];cf=observation['camera']['fields']
        if not -.0002<=age<=tick+.0002 or abs(f['_lastFixedUpdateTime']-cf['_lastFixedUpdateTime'])>.0002:
            raise ValueError('alarm_shooter_original_reference_clock')
        cam,reason=reference if reference is not None else camera_x_bounds(observation,times,player,trajectory_states)
        if cam is None:return None,reason
        camera_low,camera_high=cam
        age=np.clip(age,0.,tick);steps=np.floor((age+np.asarray(times)+1e-8)/tick).astype(int)
        local=np.float32(f['_localPos']['x']);target=np.float32(f['_targetPos']['x'])
        delay=np.float32(f['_delayTime']);before=np.float32(f['_beforeShootTime']);after=np.float32(f['_afterShootTime'])
        timer=np.float32(f['_shootTimer']);index=f['_bulletIndex'];shots=[]
        low=[xy(f['_lastPosition'])];high=[low[0].copy()];modes=[mode]
        for k in range(1,int(steps[-1])+1):
            dt=np.float32(tick);pose_local=None
            if mode=='movein':
                if delay>0:delay=np.float32(delay-dt)
                else:
                    local=np.float32(local-np.float32(np.float32(f['_shootMoveSpeed']*direction)*dt))
                    if direction>0 and local<=target or direction<0 and local>=target:
                        # Source snaps this tick's Transform to target X but
                        # keeps the overshot _localPos for the Attack ticks.
                        pose_local=target;mode='attack';timer=np.float32(0.);index=0
            elif mode=='attack':
                if before>0:before=np.float32(before-dt)
                elif index<len(bullets):
                    timer=np.float32(timer+dt)
                    if timer>=f['_shootInteralTime']:
                        # ShootBullet does not reset _shootTimer. Subsequent
                        # entries therefore fire on consecutive source ticks.
                        shots.append(dict(tick=k,index=index,parameter=bullets[index],local_x=float(local),
                            y=float(f['_lastPosition']['y']),seconds=max(0.,k*tick-age)))
                        index+=1
                else:mode='leave'
            elif after>0:after=np.float32(after-dt)
            elif f['_shootLeaveSpeed']>0:
                local=np.float32(local-np.float32(np.float32(f['_shootLeaveSpeed']*direction)*dt))
            else:local=np.float32(local+np.float32(np.float32(f['_shootMoveOutSpeed']*direction)*dt))
            if pose_local is None:pose_local=local
            low.append(np.array([np.float32(min(camera_low[k-1],camera_low[k])+pose_local),f['_lastPosition']['y']]))
            high.append(np.array([np.float32(max(camera_high[k-1],camera_high[k])+pose_local),f['_lastPosition']['y']]))
            modes.append(mode)
        previous=xy(f['_secondLastPosition']);physical=xy(f['_lastPosition'])
        correction=xy(enemy['position'])-(previous+(physical-previous)*(age/tick))
        alpha=np.clip((age+np.asarray(times)-steps*tick)/tick,0.,1.)[:,None]
        lo=np.asarray([previous,*low[:-1]])[steps]*(1-alpha)+np.asarray(low)[steps]*alpha+correction
        hi=np.asarray([previous,*high[:-1]])[steps]*(1-alpha)+np.asarray(high)[steps]*alpha+correction
        numeric=8*float(np.max(np.abs(np.spacing(np.asarray([lo,hi],dtype=np.float32)))))+.0001
        return dict(low=lo,high=hi,shots=shots,camera=cam,steps=steps,age=age,padding=numeric,modes=modes),None
    except (KeyError,ValueError)as error:return None,str(error)


def planar_arc_cloud(points,lower,upper):
    """Exact coordinate extrema of each time-indexed planar point cloud."""
    x,y=points[...,0],points[...,1];radius=np.hypot(x,y);theta=np.arctan2(y,x)
    a=np.stack((x*math.cos(lower)-y*math.sin(lower),x*math.sin(lower)+y*math.cos(lower)),axis=-1)
    b=np.stack((x*math.cos(upper)-y*math.sin(upper),x*math.sin(upper)+y*math.cos(upper)),axis=-1)
    lo=np.minimum(a,b);hi=np.maximum(a,b)
    for angle,axis,sign in ((0.,0,1),(math.pi/2,1,1),(math.pi,0,-1),(3*math.pi/2,1,-1)):
        inside=np.ceil((lower+theta-angle)/(2*math.pi))<=np.floor((upper+theta-angle)/(2*math.pi))
        target=hi if sign>0 else lo
        target[...,axis]=np.where(inside,sign*radius,target[...,axis])
    return lo.min(axis=1),hi.max(axis=1)


@lru_cache(maxsize=1)
def alarm_laser_template():
    """Original 9c9c015e... prefab, in bullet-root coordinates.

    Box -1350697636545865310, scale 4219237319812200197 and position
    -4147049911155230957. Parent/box rotations are identity. Scale and
    translation share a Transform; use the full independent curve envelope.
    These are numeric collision parameters, not rendered reference boxes.
    """
    keys=[dict(time=0.,value=0.,in_tangent=0.,out_tangent=1.,weighted_mode='None: 0'),
          dict(time=.7003629803657532,value=1.1066869497299194,
               in_tangent=.008690797723829746,out_tangent=.008690797723829746,weighted_mode='None: 0'),
          dict(time=1.,value=1.,in_tangent=-.659838080406189,out_tangent=-.659838080406189,weighted_mode='None: 0')]
    s0,s1=np.array(curve_range(keys))*1.5
    center=np.array([.004333376884460449,-.014296114444732666])
    size=np.array([1.1370692253112793,.19292882084846497])
    corners=center+np.array([[-1,-1],[1,-1],[1,1],[-1,1]])*size/2
    points=np.concatenate([corners*np.array([scale,1.])+np.array([translation,0.])
                           for scale in (s0,s1)for translation in (0.,.5)])
    points.setflags(write=False)
    return points


def alarm_shooter(enemy,times,observation,player,trajectory_states=None,reference=None):
    """Original moving body and all future bullets, before they exist."""
    from arena_privileged_model import rows,xy,Hazard
    try:
        path,reason=alarm_shooter_path(enemy,times,observation,player,trajectory_states,reference)
        if path is None:return None,reason
        hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
        if (len(hurt)!=1 or hurt[0]['type']!='SphereCollider'or hurt[0]['name']!='Device'or
                hurt[0].get('damage_kind')!='enemy_callback'or hurt[0].get('damage_owner')!=enemy['id']or
                not hurt[0]['active']or not hurt[0]['enabled']):
            raise ValueError('alarm_shooter_original_device_sphere')
        c=hurt[0];chain=next((v for v in rows(enemy['bullet_geometry']['chains'])if v['id']==c['id']),{})
        whitelist={'UnityEngine.Transform','UnityEngine.SpriteRenderer','UnityEngine.SphereCollider',
                   'EnemyBaseCollider','EnemyAlarmShooter'}
        if (not chain.get('complete')or not chain.get('includes_native_components')or
                any(name not in whitelist for node in rows(chain['nodes'])for name in rows(node['scripts']))):
            raise ValueError('alarm_shooter_unverified_damage_transform_chain')
        if trajectory_states is None:
            _,trajectory_states,valid=player.trajectory(times)
            if not valid:raise ValueError('alarm_shooter_unsupported_actor_path')
        tick=player.tick;steps=path['steps'];camera_low,camera_high=path['camera'];generated=[]
        for shot in path['shots']:
            parameter=shot['parameter'];born=shot['tick'];query=np.array([shot['seconds']])
            if (not all(math.isfinite(parameter[k])for k in ('_bullutSpeed','_bullutSpeedAcc','_bullutTargetY','_scale'))or
                    parameter['_pointToNinja']not in (True,False)):
                raise ValueError('alarm_shooter_native_bullet_parameter_domain')
            spawn_low=min(camera_low[born-1],camera_low[born])+shot['local_x']
            spawn_high=max(camera_high[born-1],camera_high[born])+shot['local_x']
            if parameter['_pointToNinja']:
                actual=observation['role']['fields']['_lastRoleObjPos']
                a,b=role_reference_rectangles(times,trajectory_states,query,actual)
                lower=a[0]-np.array([spawn_high,shot['y']]);upper=b[0]-np.array([spawn_low,shot['y']])
            else:
                a,b=role_reference_bounds(times,trajectory_states,query,observation['state']['position'])
                lower=np.array([a[0]-spawn_high,parameter['_bullutTargetY']])
                upper=np.array([b[0]-spawn_low,parameter['_bullutTargetY']])
            if np.all(lower<=0)and np.all(upper>=0):angle_lo,angle_hi=-math.pi,math.pi
            else:
                corners=np.array([[x,y]for x in (lower[0],upper[0])for y in (lower[1],upper[1])])
                angles=np.arctan2(corners[:,1],corners[:,0]);middle=math.atan2(sum(lower[1:]+upper[1:]),lower[0]+upper[0])
                angles=middle+(angles-middle+math.pi)%(2*math.pi)-math.pi
                angle_lo,angle_hi=float(min(angles)),float(max(angles))
            count=int(steps[-1])-born+2;speed=np.float32(parameter['_bullutSpeed']);acc=np.float32(parameter['_bullutSpeedAcc'])
            distances=[0.];distance=np.float32(0.)
            for _ in range(max(0,count)):
                speed=np.float32(speed+np.float32(acc*np.float32(tick)))
                distance=np.float32(distance+np.float32(np.float32(tick)*speed));distances.append(float(distance))
            flight=np.maximum(0,steps-born)
            samples=np.array(distances)[np.clip(flight[:,None]+np.array([-1,0,1]),0,len(distances)-1)]
            low_distance=samples.min(axis=1);high_distance=samples.max(axis=1)
            scale=parameter['_scale']
            if np.float32(np.float32(3.)*np.float32(np.float32(scale)*np.float32(scale)))<np.float32(9.999999439624929e-11):scale=1.
            # UpdateRotation's default forward is LEFT; negative initial speed
            # adds another half turn. Acceleration does not re-aim the shot.
            orientation=1. if parameter['_bullutSpeed']<0 else -1.
            template=alarm_laser_template()*scale*orientation
            points=np.tile(template[None,:,:],(len(times),2,1))
            points[:,:len(template),0]+=low_distance[:,None]
            points[:,len(template):,0]+=high_distance[:,None]
            lo,hi=planar_arc_cloud(points,angle_lo,angle_hi)
            n=np.minimum(steps,len(camera_low)-1);previous=np.maximum(0,n-1)
            lo+=np.column_stack((np.minimum(camera_low[n],camera_low[previous])+shot['local_x'],np.full(len(times),shot['y'])))
            hi+=np.column_stack((np.maximum(camera_high[n],camera_high[previous])+shot['local_x'],np.full(len(times),shot['y'])))
            pad=path['padding']*2+.0001+max(1,count)*np.finfo(np.float32).eps*max(1.,max(abs(v)for v in distances))*4
            active=np.asarray(times)>=max(0.,shot['seconds']-tick)
            generated.append(Hazard('spawn:'+str(enemy['id'])+':'+str(shot['index']),enemy['id'],'EnemyBullutLaser',
                (lo+hi)/2,(hi-lo)/2+pad,active,
                'EnemyAlarmShooter.ShootBullet/EnemyBullut.ResetEnemyInfo; pending native shot and original 9c9c015e prefab envelope',
                True,'aabb'))
        offset=xy(c['center'])-xy(enemy['position'])
        geometry={c['id']:((path['low']+path['high'])/2+offset,
                           (path['high']-path['low'])/2+xy(c['extents'])+path['padding'])}
        zero=np.zeros((len(times),2))
        return (zero,np.zeros(len(times)),
                'EnemyAlarmShooter.FixedUpdateMovement; original camera-relative MoveIn/Attack/Leave and complete future shot queue',
                np.ones(len(times),bool),geometry,dict(generated_hazards=generated,shots=path['shots'])),None
    except (KeyError,ValueError)as error:return None,str(error)


def brambles_path(enemy,times,observation,player,trajectory_states=None):
    """Original lift/stab reducer, retaining the unknown callback phase.

    The original Lua hotfix uses a GameController logic coroutine, with its
    instance ID and actual countdown. Legacy captures retain the bounded
    unknown remaining warning duration; no observed animation age is guessed.
    """
    from arena_privileged_model import rows,xy,timer_ticks
    try:
        f=enemy['fields'];binding=enemy['brambles'];render=binding['render'];actions=rows(binding['actions'])
        mode=int(str(f['_currState']).rsplit(':',1)[1]);index=f['_currParamIndex'];axis=xy(binding['axis_y'])
        if (mode not in range(7)or not actions or binding.get('actions_truncated')or
                not -1<=index<len(actions)or mode!=0 and index<0):
            raise ValueError('brambles_original_action_sequence')
        if (not render['direct_parent']or any(abs(render['rotation'][a])>1e-4 for a in ('x','y','z'))or
                any(abs(render['scale'][a]-1.)>1e-4 for a in ('x','y','z'))or
                abs(axis[0])+abs(binding['axis_y']['z'])>1e-5 or abs(axis[1])<1e-5 or
                abs(render['position']['x'])+abs(render['position']['z'])>1e-5):
            raise ValueError('brambles_unverified_render_transform')
        for action in actions:
            kind=int(str(action['_paramType']).rsplit(':',1)[1])
            if (kind not in (0,1)or not all(math.isfinite(action[k])for k in
                    ('_moveOrStabSpeed','_moveOrStabMaxDis','_toNextActionWaitTime','_stabStayTime','_stabBackSpeed'))or
                    action['_moveOrStabMaxDis']<0):raise ValueError('brambles_native_action_parameter_domain')
        if mode and binding['action']!=actions[index]:raise ValueError('brambles_current_action_disagreement')
        if (binding.get('blocks_truncated')or
                len(rows(binding['blocks']))!=f['_totalBrambleBlockNum']):
            raise ValueError('brambles_future_uninstantiated_blocks')
        tick=player.tick;age=observation['state']['time']-f['_lastFixedUpdateTime']
        if not -.0002<=age<=tick+.0002:raise ValueError('brambles_original_parent_clock')
        values=[f[k]for k in ('_waitTime','_currUpDis','_stabStayTime','_groundY')]
        if not all(math.isfinite(v)for v in values):raise ValueError('brambles_native_phase_parameter_domain')
        age=np.clip(age,0.,tick);steps=np.floor((age+np.asarray(times)+1e-8)/tick).astype(int);count=int(steps[-1])
        lower=upper=None
        if mode==0:
            if trajectory_states is None:
                _,trajectory_states,valid=player.trajectory(times)
                if not valid:raise ValueError('brambles_unsupported_actor_activation_path')
            query=np.maximum(0.,np.arange(count+1)*tick-age)
            lower,upper=role_reference_bounds(times,trajectory_states,query,observation['role']['fields']['_lastRoleObjPos'])
        current=np.float32(f['_lastPosition']['y']);previous=np.float32(f['_secondLastPosition']['y'])
        original_render=float(render['position']['y']);correction=enemy['position']['y']-(previous+(current-previous)*(age/tick))
        maximum_warning=math.ceil(.3/tick)+2
        warning_ticks=range(maximum_warning+1)
        if 'warning'in binding:
            warning=binding['warning'];implementation=warning['implementation']
            if implementation not in ('lua_fixed_coroutine','native_delay'):
                raise ValueError('brambles_original_warning_coroutine_binding')
            if implementation=='lua_fixed_coroutine':
                matches=rows(warning['matches'])
                if (mode!=6 and warning.get('id')not in ('',None)or mode==6 and
                        (warning.get('id')in ('',None)or len(matches)!=1 or warning['controllers']!=1 or
                         not warning['processing']or warning.get('truncated'))):
                    raise ValueError('brambles_original_warning_coroutine_binding')
                if mode==6:
                    co=matches[0];cf=co['fields']
                    if (co['type']!='NewCoroutine'or co['stack_count']!=1 or str(cf['ID'])!=warning['id']or
                            any(int(str(cf[k]).rsplit(':',1)[1])!=v for k,v in (('state',0),('nowStep',1),('nextStep',1)))or
                            cf['hasOwner']or not 0<=cf['delayTime']<=np.float32(.3)+1e-6):
                        raise ValueError('brambles_original_warning_coroutine_binding')
                    if cf['delayTime']>0:
                        remaining=timer_ticks(cf['delayTime'],tick,False)
                        # Executor and enemy update order can place the
                        # first stab in the expiry tick or the next one.
                        warning_ticks=range(max(0,remaining-1),remaining+1)
        # y, previous-y, local-render-y, phase, parameter, wait, lift-distance,
        # stab-stay, warning fixed ticks still blocked.
        initial=(float(current),float(previous),original_render,mode,index,f['_waitTime'],f['_currUpDis'],f['_stabStayTime'],0)
        states={initial[:-1]+(warning,)for warning in warning_ticks}if mode==6 else{initial}
        history=[states]
        def next_action(s):
            y,prev,local,state,param,wait,up,stay,warn=s;param=(param+1)%len(actions);a=actions[param]
            if int(str(a['_paramType']).rsplit(':',1)[1])==0:
                return {(y,prev,local,1,param,wait,0.,stay,0)}
            return {(y,prev,local,6,param,wait,up,stay,w)for w in range(max(0,math.floor(.3/tick)-1),maximum_warning+1)}
        for n in range(1,count+1):
            following=set()
            for s in states:
                y,prev,local,state,param,wait,up,stay,warn=s;prev=y
                if state==0:
                    direction=observation['camera']['direction'];x=enemy['position']['x'];distance=enemy['custom']['_activateDistance']
                    a,b=(x-upper[n])*direction,(x-lower[n])*direction;lo,hi=min(a,b),max(a,b)
                    if lo<distance:following.update(next_action((y,prev,local,state,param,wait,up,stay,warn)))
                    if hi>=distance:following.add((y,prev,local,state,param,wait,up,stay,warn))
                    continue
                action=actions[param];dt=np.float32(tick)
                if state==6:
                    if warn>0:
                        following.add((y,prev,local,state,param,wait,up,stay,warn-1));continue
                    state=2
                if state==1:
                    y=np.float32(np.float32(y)+np.float32(np.float32(action['_moveOrStabSpeed'])*dt))
                    up=np.float32(np.float32(up)+np.float32(np.float32(abs(action['_moveOrStabSpeed']))*dt))
                    if abs(up)>=action['_moveOrStabMaxDis']:
                        # Original correction is world UP even for a negative
                        # configured speed; preserve that source asymmetry.
                        y=np.float32(y+np.float32(np.float32(action['_moveOrStabMaxDis'])-up))
                        up=action['_moveOrStabMaxDis'];wait=action['_toNextActionWaitTime'];state=5
                elif state==2:
                    local=np.float32(np.float32(local)+np.float32(np.float32(abs(action['_moveOrStabSpeed']))*dt))
                    world_y=np.float32(np.float32(y)+np.float32(np.float32(axis[1])*local))
                    # Original rodata 0x11b2110 is 1.8f, not the thorn's
                    # visual tip or its local collider offset.
                    ground=np.float32(np.float32(f['_groundY'])+np.float32(1.8))
                    if f['_flip']and world_y<=ground:
                        local=np.float32((ground-np.float32(y))/np.float32(axis[1]));state=3;stay=action['_stabStayTime']
                    elif local>=action['_moveOrStabMaxDis']:
                        local=action['_moveOrStabMaxDis'];state=3;stay=action['_stabStayTime']
                elif state==3:
                    stay=np.float32(np.float32(stay)-dt)
                    if stay<=0:state=4
                elif state==4:
                    local=np.float32(np.float32(local)-np.float32(np.float32(abs(action['_stabBackSpeed']))*dt))
                    if local<=0:local=0.;state=5
                elif state==5:
                    wait=np.float32(np.float32(wait)-dt)
                    if wait<=0:
                        following.update(next_action((y,prev,local,state,param,wait,up,stay,warn)));continue
                following.add(tuple(float(v)if isinstance(v,np.floating)else v for v in (y,prev,local,state,param,wait,up,stay,warn)))
            states=following
            if not states or len(states)>512:raise ValueError('brambles_callback_phase_envelope_budget')
            history.append(states)
        lo=[];hi=[]
        for t,n in zip(times,steps):
            alpha=np.clip((age+t-n*tick)/tick,0.,1.)
            cloud=np.asarray([[axis[0]*(s[2]-original_render),
                s[1]+(s[0]-s[1])*alpha+correction-enemy['position']['y']+axis[1]*(s[2]-original_render)]for s in history[n]])
            lo.append(cloud.min(axis=0));hi.append(cloud.max(axis=0))
        numeric=8*max(abs(float(np.spacing(np.float32(enemy['position'][a]))))for a in ('x','y'))+.0001
        return (np.asarray(lo),np.asarray(hi),numeric),None
    except (KeyError,ValueError)as error:return None,str(error)


def brambles_child(enemy,times,observation,player,trajectory_states=None,context=None):
    from arena_privileged_model import rows,xy
    try:
        binding=enemy['brambles_owner'];owner=next((e for e in rows(observation['enemies'])if e['id']==binding['id']and e['type']=='EnemyBrambles'),None)
        if (owner is None or owner['info_identity']!=binding['info_identity']or not binding['under_render']or
                owner['fields'].get('_dead')or owner['fields'].get('_isRecycled')):
            raise ValueError('brambles_child_original_live_parent')
        cache=context.setdefault('brambles_paths',{})if context is not None else{}
        if owner['id']not in cache:cache[owner['id']]=brambles_path(owner,times,observation,player,trajectory_states)
        path,reason=cache[owner['id']]
        if path is None:return None,reason
        movement=enemy['type']=='EnemyBrambleCollider'
        colliders=[c for c in rows(enemy['colliders'])if c.get('native_movement_callback')=='bramble_contact']if movement else[
            c for c in rows(enemy['colliders'])if c.get('damage_kind')]
        if not colliders or any(c['type']!='BoxCollider'or not c['enabled']or not c['active']or c.get('depth_tilt')or
                movement and c.get('movement_owner')!=enemy['id']for c in colliders):
            raise ValueError('brambles_child_original_planar_boxes')
        lo,hi,padding=path;geometry={c['id']:((lo+hi)/2+xy(c['center']),(hi-lo)/2+xy(c['extents'])+padding)for c in colliders}
        zero=np.zeros((len(times),2))
        return (zero,np.zeros(len(times)),
                'EnemyBrambles.FixedUpdateMovement/ToNextAction; original parent lift/stab and bounded callback phase'+
                ('; avoid native bramble movement contact'if movement else'; original generated thorn box'),
                np.ones(len(times),bool),geometry),None
    except (KeyError,ValueError)as error:return None,str(error)


def rolling_path(enemy,times,observation,player,activation_tick=None):
    """Source-order fall, slope projection, wall stop and native pit entry.

    The actual current/next-ground chain is read without invoking a lookup or
    changing the game. Missing links and unproved ready branches stop
    prediction; the current slope is never extended over an unknown seam.
    """
    from arena_privileged_model import rows,xy
    f=enemy['fields'];initial=int(f['_enemyState'].rsplit(':',1)[1]);mode=initial
    if mode not in (0,1,2,3,4,5):return None,'rolling_phase:'+str(mode)
    if observation.get('camera',{}).get('direction')!=1:
        return None,'rolling_original_run_direction'
    hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
    if (len(hurt)!=1 or hurt[0]['type']!='SphereCollider' or hurt[0]['damage_kind']!='enemy_tag'
            or hurt[0].get('damage_owner') is not None or not hurt[0]['active'] or not hurt[0]['enabled']
            or hurt[0]['name']!=enemy['name'] or np.linalg.norm(xy(hurt[0]['center'])-xy(enemy['position']))>.0001
            or max(abs(hurt[0]['extents'][a]-f['_radius'])for a in ('x','y','z'))>.0001):
        return None,'rolling_original_root_sphere'
    # State None replaces _currentBlock at activation; a recycled instance
    # can retain another spawn's field before that source branch runs.
    support=enemy.get('native_support') if mode==0 else enemy.get('rolling_support')
    if not support or not(support['is_line'] or support['is_ground']):
        return None,'rolling_current_block_missing'
    blocks=list(rows(enemy.get('rolling_blocks'))) or [support]
    if enemy.get('rolling_chain_truncated') is False:
        # A fast rock can reach an edge before the next native collider has
        # been instantiated. The original resolved stage already specifies
        # that continuation. Retain its possible live motion conservatively;
        # if the real next link stays null, native code recycles the rock.
        # Never extend a cyclic/truncated live graph or invent a missing floor.
        terrain=rows(observation.get('terrain'));tail=blocks[-1]
        matches=[i for i,b in enumerate(terrain)if
                 np.linalg.norm(xy(b['start'])-xy(tail['start']))<.001 and
                 np.linalg.norm(xy(b['finish'])-xy(tail['finish']))<.001]
        if len(matches)==1:
            from arena_privileged_model import phase
            for b in terrain[matches[0]+1:]:
                kind=phase(b['kind'])
                if kind not in ('line','ground','link') or np.linalg.norm(xy(b['start'])-xy(blocks[-1]['finish']))>.001:
                    break
                blocks.append(dict(id=b['id'],start=b['start'],finish=b['finish'],is_line=kind=='line',is_ground=kind=='ground',
                    info=dict(_isDeadBlockOffsetY=b['death_offset_y']),resolved_before_native_instantiation=True))
    origin=next((i for i,b in enumerate(blocks)if b['id']==support['id']),None)
    if origin is None:return None,'rolling_native_chain_origin'
    if any(b['finish']['x']<b['start']['x'] or b['start']['z']!=b['finish']['z'] for b in blocks):
        return None,'rolling_unsupported_native_block'
    if any(abs(blocks[i]['finish']['x']-blocks[i+1]['start']['x'])>.001 for i in range(len(blocks)-1)):
        return None,'rolling_discontinuous_native_chain'
    if f['_readyToFall']:return None,'rolling_ready_rebound_unverified'
    if abs(f['_velocity']['z'])>1e-8 or abs(f['_recordVelocity']['z'])>1e-8:
        return None,'rolling_spatial_velocity'
    age=observation['state']['time']-f['_lastFixedUpdateTime']
    if not -.0002<=age<=player.tick+.0002:return None,'rolling_original_fixed_clock'
    current=origin;block_degree=np.float32(f['_blockDegree']);fall_y=np.float32(f['_fallPosY'])
    def degree(block):
        d=xy(block['finish'])-xy(block['start']);length=np.float32(np.linalg.norm(d))
        if length<=0:return np.float32(0.)
        return np.float32(np.float32(math.acos(np.clip(np.float32(d[0])/length,-1,1)))*np.float32(57.295780181884766))
    if abs(block_degree-degree(support))>.005 and mode not in (0,4,5):return None,'rolling_native_block_angle'
    def ground(block,x):
        a,b=block['start'],block['finish'];width=np.float32(b['x']-a['x'])
        if abs(width)<=1e-5:return np.float32(a['y'])
        rise=np.float32(b['y']-a['y']);dx=np.float32(x-np.float32(a['x']))
        return np.float32(np.float32(a['y'])+np.float32(np.float32(dx*rise)/width))
    if initial in (1,3) and abs(fall_y-ground(support,np.float32(f['_lastPosition']['x'])))>.001:
        return None,'rolling_native_landing_height'
    velocity=np.array([f['_velocity'][axis]for axis in ('x','y')],np.float32)
    record=np.array([f['_recordVelocity'][axis]for axis in ('x','y')],np.float32)
    real=np.array([f['_realVelocity'][axis]for axis in ('x','y')],np.float32)
    gravity=np.float32(f['_gravity']);radius=np.float32(f['_radius']);height=np.float32(f['_height'])
    lengthen=player.rules.get('ground_lengthen')
    if lengthen is None:return None,'rolling_native_lookup_range_missing'
    failure=None;step=0;max_speed=float(np.linalg.norm(velocity))
    def next_index(i):
        nonlocal failure
        if i+1>=len(blocks):failure='rolling_native_next_block_missing';return i
        return i+1
    def lookup(x):
        nonlocal failure
        for i,block in enumerate(blocks):
            if np.float32(np.float32(block['start']['x'])+np.float32(lengthen))<=x<=np.float32(np.float32(block['finish']['x'])+np.float32(lengthen)):
                return i
        failure='rolling_native_lookup_outside_chain';return current
    def pit(index):
        nonlocal current,mode,velocity
        current=index;mode=4;velocity=real.copy()
        velocity[1]=np.float32(velocity[1]-np.float32(np.float32(f['_speedY'])*np.float32(.5)))
    def update(pos,dt):
        nonlocal mode,velocity,record,real,current,block_degree,fall_y,failure,step,max_speed
        dt=np.float32(dt);step+=1
        if failure or mode==5:return pos,0.
        block=blocks[current];a,b=block['start'],block['finish']
        if mode==0:
            if step==activation_tick:
                current=lookup(pos[0]);block=blocks[current];block_degree=degree(block)
                fall_y=ground(block,pos[0]);mode=3
        elif mode in (1,3):
            gain=np.float32(3.5 if mode==1 else 1.)
            velocity[1]=np.float32(velocity[1]-np.float32(np.float32(gravity*gain)*dt))
            max_speed=max(max_speed,float(np.linalg.norm(velocity)))
            pos[1]=np.float32(pos[1]+np.float32(velocity[1]*dt))
            if np.float32(np.float32(pos[1]-radius)-height)<=ground(block,pos[0]):
                pos[1]=np.float32(np.float32(fall_y+radius)+height)
                if record[0]==0:record=velocity.copy()
                else:velocity=record.copy()
                mode=2
        elif mode==4:
            velocity[1]=np.float32(velocity[1]-np.float32(np.float32(gravity*np.float32(5.))*dt))
            max_speed=max(max_speed,float(np.linalg.norm(velocity)))
            if np.float32(pos[0]-np.float32(a['x']))<radius:
                pos=np.asarray(pos+velocity*dt,dtype=np.float32)
            elif block['info']['_isDeadBlockOffsetY']!=0:
                pos[1]=np.float32(pos[1]+np.float32(velocity[1]*dt))
            else:
                current=lookup(pos[0]);block=blocks[current];block_degree=degree(block)
                fall_y=ground(block,pos[0]);mode=3
        else:
            if np.float32(pos[0]+radius)>=np.float32(b['x']):
                j=next_index(current);n=blocks[j]
                if failure:return pos,0.
                if n['start']['x']==n['finish']['x'] and n['start']['y']<n['finish']['y']:
                    pos[0]=np.float32(np.float32(n['finish']['x'])-radius);mode=5;return pos,0.
            if pos[0]>=np.float32(b['x']):
                j=next_index(current);n=blocks[j]
                if failure:return pos,0.
                if n['start']['x']==n['finish']['x'] and n['start']['y']>n['finish']['y']:
                    pit(next_index(j));return pos,0.
            target=lookup(pos[0])
            if failure:return pos,0.
            if target!=current:
                n=blocks[target]
                if n['info']['_isDeadBlockOffsetY']!=0:
                    pit(target);return pos,0.
                if n['start']['x']==n['finish']['x']:
                    j=next_index(target)
                    if failure:return pos,0.
                    if blocks[j]['info']['_isDeadBlockOffsetY']!=0:
                        pit(j);return pos,0.
                else:current=target;block_degree=degree(n)
            velocity[1]=np.float32(velocity[1]-np.float32(gravity*dt))
            max_speed=max(max_speed,float(np.linalg.norm(velocity)))
            ratio=math.inf if velocity[1]==0 else abs(float(np.float32(velocity[0]/velocity[1])))
            degrees=np.float32(np.float32(math.atan(ratio))*np.float32(-57.295780181884766))
            angle=np.float32(np.float32(np.float32(90.)-block_degree)+degrees)
            factor=np.float32(math.cos(np.float32(angle*np.float32(.01745329238474369))))
            magnitude=np.float32(math.sqrt(np.float32(np.float32(velocity[0]*velocity[0])+np.float32(velocity[1]*velocity[1]))))
            speed=np.float32(magnitude*factor);theta=np.float32(block_degree*np.float32(.01745329238474369))
            real=np.array([np.float32(math.cos(theta)),np.float32(math.sin(theta))],np.float32)*speed*np.where(velocity>0,np.float32(1.),np.float32(-1.))
            pos=np.asarray(pos+real*dt,dtype=np.float32)
        return pos,0.
    positions,angles=native_steps(enemy,times,observation,update)
    if failure:return None,failure
    rounding=(2*abs(float(np.spacing(np.float32(observation['state']['time']))))*max(1.,max_speed)
              +8*float(np.max(np.abs(np.spacing(positions.astype(np.float32)))))+.0001)
    return (positions-xy(enemy['position']),angles,
            'EnemyRollingBase.ProcessState/MoveOnGround; native gravity, slope projection, wall stop and linked pit entry',
            None,None,dict(position_padding=rounding)),None


def rolling(enemy,times,observation,player,trajectory_states=None):
    """Enclose all original role-reference activation ticks for state None."""
    f=enemy['fields'];mode=int(f['_enemyState'].rsplit(':',1)[1])
    if mode!=0:return rolling_path(enemy,times,observation,player)
    role=observation['role']['fields'];actual=role.get('_lastRoleObjPos')
    if not player.native_samples or abs(f['_lastFixedUpdateTime']-role['_lastFixedUpdateTime'])>.0002:
        return None,'rolling_original_role_clock'
    if actual is None or abs(actual['x']-player.initial.physical_x-player.initial.offset_render)>abs(player.speed)*player.tick+.025:
        return None,'rolling_original_role_reference'
    if trajectory_states is None:
        _,trajectory_states,valid=player.trajectory(times)
        if not valid:return None,'rolling_player_reference_unsupported'
    age=np.clip(observation['state']['time']-f['_lastFixedUpdateTime'],0,player.tick)
    count=int(math.floor((age+times[-1]+1e-8)/player.tick));query=np.maximum(0.,np.arange(1,count+1)*player.tick-age)
    lower,upper=role_reference_bounds(times,trajectory_states,query,actual)
    threshold=f['_lastPosition']['x']-f['_activeDistance'];possible=certain=None
    for k in range(1,count+1):
        if possible is None and upper[k-1]>threshold:possible=k
        if lower[k-1]>threshold:certain=k;break
    activation=[None]
    if possible is not None:
        if (certain or count)-possible>8:return None,'rolling_activation_uncertainty'
        activation=list(range(possible,(certain or count)+1))
        if certain is None:activation.append(None)
    paths=[]
    for activation_tick in activation:
        path,reason=rolling_path(enemy,times,observation,player,activation_tick)
        if path is None:return None,reason
        paths.append(path)
    positions=np.array([p[0]for p in paths]);lower,upper=positions.min(axis=0),positions.max(axis=0)
    middle=(lower+upper)/2;meta=dict(position_padding=max(p[5]['position_padding']for p in paths),envelope_spread=(upper-lower)/2)
    return (middle,np.zeros(len(times)),paths[0][2]+'; native role-distance activation envelope',None,None,meta),None


def spider_entry(enemy,times,observation,player,trajectory_states=None):
    """None:9 is a stationary high root, not a permanently harmless spider.

    Original ProcessState compares X against cached GetRoleObjPos plus the
    configured activation distance. Enclose every feasible activation tick
    around the physical/render reference ordering, then run the unchanged
    original drop/flex reducer. This is conditional on no damage feedback;
    Bite:8 has its own render-child curves and remains explicitly unsupported.
    """
    from arena_privileged_model import rows,xy,spider_positions
    f=enemy['fields'];tick=player.tick
    if observation.get('camera',{}).get('direction')!=1:
        return None,'spider_original_run_direction'
    if f.get('_renderType')!=0 or enemy.get('custom_type')!='EnemySpiderDataStruct':
        return None,'spider_unverified_entry_render'
    hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
    if len(hurt)!=1 or any(c['type']!='SphereCollider' or c.get('damage_owner')!=enemy['id']
            or not c['enabled'] or not c['active'] or np.linalg.norm(xy(c['center'])-xy(enemy['position']))>.0001
            or max(abs(c['scale'][a]-enemy['scale'][a])for a in ('x','y','z'))>.0001 for c in hurt):
        return None,'spider_unverified_entry_shape'
    role=observation['role']['fields'];actual=role.get('_lastRoleObjPos')
    age=observation['state']['time']-f['_lastFixedUpdateTime']
    if not player.native_samples or not -.0002<=age<=tick+.0002 or abs(f['_lastFixedUpdateTime']-role['_lastFixedUpdateTime'])>.0002:
        return None,'spider_original_reference_clock'
    if actual is None or abs(actual['x']-player.initial.physical_x-player.initial.offset_render)>abs(player.speed)*tick+.025:
        return None,'spider_original_role_reference'
    if trajectory_states is None:
        _,trajectory_states,valid=player.trajectory(times)
        if not valid:return None,'spider_player_reference_unsupported'
    # This trigger consumes actor position, not a fixed running-speed timer.
    # The physical trajectory below already includes slope acceleration and
    # candidate flips/slides; requiring vx==baseSpeed rejects valid slopes.
    age=np.clip(age,0,tick);count=int(math.floor((age+times[-1]+1e-8)/tick))
    query=np.maximum(0.,np.arange(1,count+1)*tick-age)
    lower,upper=role_reference_bounds(times,trajectory_states,query,actual)
    threshold=f['_lastPosition']['x']-enemy['custom']['_activateDistance'];possible=certain=None
    for k in range(1,count+1):
        if possible is None and upper[k-1]>threshold:possible=k
        if lower[k-1]>threshold:certain=k;break
    activation=[None]
    if possible is not None:
        if (certain or count)-possible>8:return None,'spider_activation_uncertainty'
        activation=list(range(possible,(certain or count)+1))
        if certain is None:activation.append(None)
    ys=np.asarray([spider_positions(enemy,times,stamp=observation['state']['time'],tick=tick,activation_tick=k)for k in activation])
    lower,upper=ys.min(axis=0),ys.max(axis=0)
    return ((lower+upper)/2-enemy['position']['y'],(upper-lower)/2+.0002),None


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
        lower,upper=role_reference_bounds(times,trajectory_states,query,actual)
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


def suspend_path(enemy,times,observation):
    """Original world-space hover reducer and both fixed-position samples."""
    from arena_privileged_model import phase,xy
    f=enemy['fields'];mode=phase(f['_state'])
    if mode not in ('stay','move'):return None,'suspend_phase:'+mode
    vy=np.float32(f['_speedY']);waiting=np.float32(f['_stayTime'])
    samples=[xy(f['_lastPosition']).astype(np.float32)]
    def update(pos,dt):
        nonlocal mode,vy,waiting
        if mode=='stay':
            waiting=np.float32(waiting-np.float32(dt))
            if waiting<=0:mode='move'
        elif vy!=0:
            y=np.float32(pos[1]+np.float32(vy*dt))
            if y>=f['_maxY']:
                if not f['_changeSpeedDirAcc']:vy=-vy
                else:vy=np.float32(vy-np.float32(f['_changeSpeedDirAcc']*dt));pos[1]=y
            elif y<=f['_minY']:
                if not f['_changeSpeedDirAcc']:vy=-vy
                else:vy=np.float32(vy+np.float32(f['_changeSpeedDirAcc']*dt));pos[1]=y
            else:pos[1]=y
        pos[0]=np.float32(pos[0]+np.float32(f['_speedX']*dt))
        samples.append(pos.copy())
        return pos,0.
    positions,angles=native_steps(enemy,times,observation,update)
    tick=observation['state']['fixedDeltaTime']
    age=np.clip(observation['state']['time']-f['_lastFixedUpdateTime'],0.,tick)
    indices=np.floor((age+np.asarray(times)+1e-8)/tick).astype(int)
    current=np.array(samples)[indices]
    previous=np.asarray([xy(f['_secondLastPosition']),*samples[:-1]])[indices]
    return (positions,angles,current,previous),None


def suspend_special(enemy,times,observation,player):
    """A source-verified generated sphere; no generic subclass aliasing."""
    from arena_privileged_model import rows,xy
    try:
        f=enemy['fields'];controller=enemy.get('suspend_controller',{})
        if controller.get('type')=='EnemyRotateElectricBall'and f.get('_movementEnable')is False:
            return rotating_ball(enemy,times,observation,player)
        if (f.get('_movementEnable')is not True or controller.get('type')!='EnemyConnectElectricBall'
                or not controller.get('id')or not controller.get('alive')or not controller.get('info_identity')):
            raise ValueError('suspend_special_unverified_or_disabled_controller')
        hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
        if (len(hurt)!=1 or hurt[0]['type']!='SphereCollider' or hurt[0]['name']!='balloon'
                or hurt[0].get('damage_kind')!='enemy_callback' or hurt[0].get('damage_owner')!=enemy['id']
                or not hurt[0]['enabled']or not hurt[0]['active']
                or np.linalg.norm(xy(hurt[0]['center'])-xy(enemy['position']))>.0001):
            raise ValueError('suspend_special_original_centered_sphere')
        numbers=[f[k]for k in ('_speedX','_speedY','_stayTime','_minY','_maxY','_changeSpeedDirAcc')]
        if not all(math.isfinite(v)for v in numbers)or f['_minY']>f['_maxY']or f['_changeSpeedDirAcc']<0:
            raise ValueError('suspend_special_native_parameter_domain')
        age=observation['state']['time']-f['_lastFixedUpdateTime']
        if not -.0002<=age<=player.tick+.0002:raise ValueError('suspend_special_original_fixed_clock')
        path,reason=suspend_path(enemy,times,observation)
        if path is None:return None,reason
        positions,angles=path[:2]
        numeric=8*max(abs(float(np.spacing(np.float32(v))))for v in positions.ravel())
        rate=max(abs(f['_speedX']),abs(f['_speedY'])+f['_changeSpeedDirAcc']*times[-1])
        numeric+=2*abs(float(np.spacing(np.float32(observation['state']['time']))))*rate+.00001
        return (positions-xy(enemy['position']),angles,
                'EnemySuspendSpecial.MyFixedUpdate/EnemySuspend.FixedUpdateMovement; original enabled generated sphere',
                None,None,dict(position_padding=numeric)),None
    except (KeyError,ValueError)as error:return None,str(error)


def rotating_path(enemy,times,observation,player):
    """Rigid assembly, source fixed-position interpolation and direct Z writes.

    Reset disables both generated children's movement. FreshElectricPosition
    runs once there, not every tick. FixedUpdateMovement then translates the
    parent and rotates its local Euler Z at NinjaSpeed*.125*rotateSpeed.
    """
    from arena_privileged_model import rows,xy
    try:
        f=enemy['fields'];binding=enemy['rigid_electric'];balls=rows(binding['balls'])
        if (not binding['parent_axes_identity']or not binding['direct_electric']or
                any(abs(binding['local_rotation'][a])>1e-4 for a in ('x','y'))or
                enemy['scale']['x']<=0 or
                abs(enemy['scale']['x']-enemy['scale']['y'])>1e-4 or
                not all(math.isfinite(enemy['scale'][a])for a in ('x','y','z'))):
            raise ValueError('rotating_electric_unverified_rigid_transform')
        if (len(balls)!=2 or len({b['id']for b in balls})!=2 or
                any(not b['direct_parent']or b['movement_enabled']is not False for b in balls)):
            raise ValueError('rotating_electric_unverified_disabled_endpoints')
        tick=player.tick;age=observation['state']['time']-f['_lastFixedUpdateTime']
        if not -.0002<=age<=tick+.0002:raise ValueError('rotating_electric_original_parent_clock')
        speed=observation['state']['speed']
        # SetStopRun changes speed data on the following actor physics tick.
        # Do not extrapolate the old speed across this pending transition.
        if observation['role']['fields'].get('_runStopped')and speed!=0:
            raise ValueError('rotating_electric_pending_actor_speed_stop')
        if not observation['role']['fields'].get('_runStopped')and speed==0:
            raise ValueError('rotating_electric_unverified_zero_or_resuming_actor_speed')
        if not all(math.isfinite(v)for v in (f['_moveSpeed'],f['_rotateSpeed'],speed,enemy['rotation_z'])):
            raise ValueError('rotating_electric_native_parameter_domain')
        angle=np.float32(binding['local_rotation']['z']);initial=float(angle)
        rate=np.float32(np.float32(np.float32(speed)*np.float32(.125))*np.float32(f['_rotateSpeed']))
        def update(pos,dt):
            nonlocal angle
            pos[0]=np.float32(pos[0]+np.float32(np.float32(f['_moveSpeed'])*np.float32(dt)))
            angle=np.float32(np.float32(angle+np.float32(rate*np.float32(dt)))%np.float32(360.))
            return pos,math.radians(float(angle)-initial)
        positions,angles=native_steps(enemy,times,observation,update)
        # Euler getter/Quaternion conversion and float32 fixedTime subtraction
        # can choose the neighbouring physical angle at a tick boundary. Keep
        # one full angular tick, plus accumulated float32 angle roundoff.
        updates=math.ceil(float(times[-1])/tick)+1
        angle_guard=abs(float(rate))*tick+updates*float(np.spacing(np.float32(360.)))*4
        numeric=8*max(abs(float(np.spacing(np.float32(v))))for v in positions.ravel())+.0001
        numeric+=2*abs(float(np.spacing(np.float32(observation['state']['time']))))*abs(f['_moveSpeed'])
        return (positions,angles,math.radians(angle_guard),numeric),None
    except (KeyError,ValueError)as error:return None,str(error)


def rotating_ball(enemy,times,observation,player):
    from arena_privileged_model import rows,xy
    try:
        owner=enemy['suspend_controller'];hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
        if (not owner.get('alive')or not owner.get('info_identity')or
                enemy['id']not in {b['id']for b in rows(owner['rigid_electric']['balls'])}):
            raise ValueError('rotating_ball_original_live_owner')
        if (len(hurt)!=1 or hurt[0]['type']!='SphereCollider'or hurt[0]['name']!='balloon'or
                hurt[0].get('damage_kind')!='enemy_callback'or hurt[0].get('damage_owner')!=enemy['id']or
                not hurt[0]['active']or not hurt[0]['enabled']or
                np.linalg.norm(xy(hurt[0]['center'])-xy(enemy['position']))>.0001):
            raise ValueError('rotating_ball_original_centered_sphere')
        predicted,reason=rotating_path(owner,times,observation,player)
        if predicted is None:return None,reason
        positions,angles,angular_guard,numeric=predicted
        offset=xy(enemy['position'])-xy(owner['position'])
        orbit=np.column_stack((offset[0]*np.cos(angles)-offset[1]*np.sin(angles),
                               offset[0]*np.sin(angles)+offset[1]*np.cos(angles)))
        pad=numeric+np.linalg.norm(offset)*min(2.,angular_guard)
        return (positions+orbit-xy(enemy['position']),np.zeros(len(times)),
                'EnemyRotateElectricBall.FixedUpdateMovement; original disabled child follows parent rigid orbit',
                None,None,dict(position_padding=pad)),None
    except (KeyError,ValueError)as error:return None,str(error)


def rotating_electric(enemy,times,observation,player):
    from arena_privileged_model import rows,xy
    try:
        predicted,reason=rotating_path(enemy,times,observation,player)
        if predicted is None:return None,reason
        positions,angles,angular_guard,numeric=predicted
        hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
        if (len(hurt)!=1 or hurt[0]['type']!='BoxCollider'or not hurt[0].get('quad')or
                hurt[0]['id']not in enemy['rigid_electric']['colliders']or
                hurt[0].get('damage_kind')!='enemy_callback'or hurt[0].get('damage_owner')!=enemy['id']or
                not hurt[0]['enabled']or hurt[0].get('depth_tilt')):
            raise ValueError('rotating_electric_original_link_box')
        c=hurt[0];f=enemy['fields'];enabled=f['_electricEnable'];generating=f['_generateElectric']
        duration=np.float32(f['_durationTimer']);interval=np.float32(f['_intervalTimer']);tick=player.tick
        if (not all(math.isfinite(v)and v>=0 for v in (duration,interval,f['_durationTime'],f['_interalTime']))):
            raise ValueError('rotating_electric_native_pulse_domain')
        if c['active']!=bool(generating and enabled):raise ValueError('rotating_electric_native_enable_disagreement')
        age=np.clip(observation['state']['time']-f['_lastFixedUpdateTime'],0.,tick)
        steps=np.floor((age+np.asarray(times)+1e-8)/tick).astype(int);n=0;active=[]
        for wanted in steps:
            while n<wanted:
                if generating:
                    if enabled:
                        duration=np.float32(duration+np.float32(tick))
                        if duration>=f['_durationTime']:enabled=False;duration=np.float32(0.)
                    else:
                        interval=np.float32(interval+np.float32(tick))
                        if interval>f['_interalTime']:enabled=True;interval=np.float32(0.)
                n+=1
            active.append(bool(generating and enabled))
        lever=max(np.linalg.norm(xy(p)-xy(enemy['position']))for p in c['quad'])
        return (positions-xy(enemy['position']),angles,
                'EnemyRotateElectricBall.FixedUpdateMovement; original rigid box, direct parent Euler and pulse clock',
                np.asarray(active),None,dict(position_padding=numeric+lever*min(2.,angular_guard))),None
    except (KeyError,ValueError)as error:return None,str(error)


def connected_electric(enemy,times,observation,player):
    """Original pulsed link between two independently moving native balls.

    The link Transform samples the endpoint Transforms in fixed-update order.
    Enclose both physical samples and their rendered interpolation; do not
    freeze the current line or predict a beam at the parent spawn position.
    """
    from arena_privileged_model import rows,xy
    try:
        f=enemy['fields'];binding=enemy['electric_connection'];balls=rows(binding['balls'])
        if binding.get('balls_truncated')or len(balls)!=2 or any(b['type']!='EnemySuspendSpecial'or b['fields'].get('_movementEnable')is not True for b in balls):
            raise ValueError('electric_connection_original_moving_endpoints')
        scale=enemy['scale']['x']
        if (not binding.get('direct_parent')or abs(enemy['rotation_z'])>1e-5 or scale<=0 or
                not all(math.isfinite(enemy['scale'][a])for a in ('x','y','z'))or
                abs(enemy['scale']['y']-scale)>1e-5 or
                any(abs(binding['local_scale'][a]-1.)>1e-5 for a in ('x','z'))):
            raise ValueError('electric_connection_modified_transform')
        root=xy(enemy['position'])
        if any(np.linalg.norm(xy(f[k])-root)>.0001 for k in ('_lastPosition','_secondLastPosition')):
            raise ValueError('electric_connection_moving_parent')
        hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
        if (len(hurt)!=1 or hurt[0]['type']!='BoxCollider'or hurt[0]['id']not in binding['colliders']or
                hurt[0].get('damage_owner')!=enemy['id']or hurt[0].get('damage_kind')!='enemy_callback'or
                not hurt[0]['enabled']or hurt[0].get('depth_tilt')):
            raise ValueError('electric_connection_original_link_box')
        c=hurt[0];tick=player.tick;age=observation['state']['time']-f['_lastFixedUpdateTime']
        if not -.0002<=age<=tick+.0002:raise ValueError('electric_connection_original_fixed_clock')
        ratio=f['_electricRatio'];duration=np.float32(f['_durationTimer']);interval=np.float32(f['_intervalTimer'])
        if (not all(math.isfinite(v)and v>=0 for v in (ratio,f['_durationTime'],f['_interalTime'],duration,interval))or ratio<=0):
            raise ValueError('electric_connection_timer_or_length_domain')
        enabled=f['_electricEnable'];generating=f['_generateElectric']
        if c['active']!=bool(enabled and generating):raise ValueError('electric_connection_native_enable_disagreement')
        age=np.clip(age,0.,tick);steps=np.floor((age+np.asarray(times)+1e-8)/tick).astype(int)
        query=np.maximum(0.,steps*tick-age)
        endpoints=[]
        for b in balls:
            if b['fields'].get('_dead')or b['fields'].get('_isRecycled'):
                raise ValueError('electric_connection_dead_or_recycled_endpoint')
            if abs(b['position']['z']-enemy['position']['z'])>1e-5:
                raise ValueError('electric_connection_spatial_endpoint')
            bf=b['fields'];child_age=observation['state']['time']-bf['_lastFixedUpdateTime']
            if not -.0002<=child_age<=tick+.0002:
                raise ValueError('electric_connection_endpoint_fixed_clock')
            if (not all(math.isfinite(bf[k])for k in ('_speedX','_speedY','_stayTime','_minY','_maxY','_changeSpeedDirAcc'))
                    or bf['_minY']>bf['_maxY']or bf['_changeSpeedDirAcc']<0):
                raise ValueError('electric_connection_endpoint_parameter_domain')
            path,reason=suspend_path(b,query,observation)
            if path is None:raise ValueError(reason)
            endpoints.append((np.minimum.reduce([path[0],path[2],path[3]]),
                              np.maximum.reduce([path[0],path[2],path[3]])))
        # Original local Y length is endpoint distance/electricRatio. Include
        # authored longitudinal offsets/overhang and full cross-section even
        # for coincident endpoints, whose rotation is still source-defined.
        width=scale*(abs(c['local_center']['x'])+c['size']['x']/2)
        length=scale*(abs(c['local_center']['y'])+c['size']['y']/2)/ratio
        if width<0 or length<0 or not math.isfinite(width+length):
            raise ValueError('electric_connection_authored_box_domain')
        a,b=endpoints
        separation=np.maximum(abs(a[0]-b[1]),abs(a[1]-b[0]))
        overhang=np.maximum(0.,length-.5)*np.linalg.norm(separation,axis=1)
        guard=width+overhang
        low=np.minimum(a[0],b[0])-guard[:,None];high=np.maximum(a[1],b[1])+guard[:,None]
        # n=0 is the original line, which may preserve a prior endpoint sample
        # while its child balls have already interpolated another render pose.
        initial=steps==0
        low[initial]=xy(c['center'])-xy(c['extents'])
        high[initial]=xy(c['center'])+xy(c['extents'])
        active=[];n=0
        for wanted in steps:
            while n<wanted:
                if generating:
                    if enabled:
                        duration=np.float32(duration+np.float32(tick))
                        if duration>=f['_durationTime']:enabled=False;duration=np.float32(0.)
                    else:
                        interval=np.float32(interval+np.float32(tick))
                        if interval>f['_interalTime']:enabled=True;interval=np.float32(0.)
                n+=1
            active.append(bool(generating and enabled))
        numeric=8*max(abs(float(np.spacing(np.float32(v))))for v in np.r_[low.ravel(),high.ravel()])+.0001
        speed=max(abs(ball['fields']['_speedX'])+abs(ball['fields']['_speedY'])+
                  ball['fields']['_changeSpeedDirAcc']*times[-1]for ball in balls)
        numeric+=2*abs(float(np.spacing(np.float32(observation['state']['time']))))*speed
        zero=np.zeros((len(times),2))
        return (zero,np.zeros(len(times)),
                'EnemyConnectElectricBall.FixedUpdateMovement/FreshElectricPosition; native endpoint and pulse envelope',
                np.asarray(active),{c['id']:((low+high)/2,(high-low)/2+numeric)}),None
    except (KeyError,ValueError)as error:return None,str(error)


def planar_arc_bounds(point, lower, upper):
    """Exact AABB of a point over a continuous planar rotation interval."""
    x,y=point;radius=math.hypot(x,y)
    if upper-lower>=2*math.pi-1e-10:
        return np.full(2,-radius),np.full(2,radius)
    direction=math.atan2(y,x)
    samples=[lower,upper]
    for extremum in (0.,math.pi/2,math.pi,3*math.pi/2):
        angle=extremum-direction
        first=math.ceil((lower-angle)/(2*math.pi))
        candidate=angle+first*2*math.pi
        if candidate<=upper:samples.append(candidate)
    angles=np.asarray(samples)+direction
    values=np.column_stack((np.cos(angles),np.sin(angles)))*radius
    return values.min(axis=0),values.max(axis=0)


def role_reference_rectangles(times,motors,query,actual):
    """Cached physical XY reference, including both original update orders."""
    physical=np.array([[m.physical_x,m.physical_y]for m in motors])
    previous=np.array([[m.previous_x,m.previous_y]for m in motors])
    offsets=np.array([[m.offset_render,0.]for m in motors])
    residual=np.array([actual[a]for a in ('x','y')])-physical[0]
    lower=np.minimum(physical,previous)+np.minimum(offsets,np.minimum(0.,residual))
    upper=np.maximum(physical,previous)+np.maximum(offsets,np.maximum(0.,residual))
    lo=np.clip(np.searchsorted(times,query,side='right')-1,0,len(times)-1)
    hi=np.clip(np.searchsorted(times,query,side='left'),0,len(times)-1)
    return np.minimum(lower[lo],lower[hi])-.025,np.maximum(upper[lo],upper[hi])+.025


def rock_tiger(enemy,times,observation,player,trajectory_states=None):
    """Original distance/aim/extend/retract with the actual head capsule.

    Head translation and root aim are fixed-update Transform writes, rather
    than BaseObject root interpolation. Unknown activation ticks and cached
    actor reference rectangles are retained as a union of complete futures.
    """
    from arena_privileged_model import rows,xy
    try:
        f=enemy['fields'];binding=enemy['rock_tiger'];data=binding['data'];head=binding['head']
        mode=int(str(f['currState']).rsplit(':',1)[-1]);tick=player.tick
        if mode not in range(1,6):raise ValueError('rock_tiger_phase')
        if not binding.get('planar_root') or not head.get('direct_parent') or not head.get('identity_rotation'):
            raise ValueError('rock_tiger_head_transform')
        root=xy(enemy['position']);scale=enemy['scale'];head_scale=head['scale']
        if (scale['x']<=0 or max(abs(scale[a]-scale['x'])for a in ('x','y','z'))>1e-5
                or max(abs(head_scale[a]-1.)for a in ('x','y','z'))>1e-5):
            raise ValueError('rock_tiger_nonuniform_or_modified_scale')
        if any(np.linalg.norm(xy(f[k])-root)>.0001 for k in ('_lastPosition','_secondLastPosition')):
            raise ValueError('rock_tiger_moving_root')
        direction=xy(f['originLookAt']);length=np.linalg.norm(direction)
        if length<1e-5 or abs(f['originLookAt']['z'])>1e-6 or abs(head['position']['z'])>1e-6:
            raise ValueError('rock_tiger_spatial_head_path')
        direction=(direction/length).astype(np.float32)
        local=xy(head['position']).astype(np.float32)
        if (abs(direction[0]*local[1]-direction[1]*local[0])>.0001 or np.dot(direction,local)<-.0001
                or mode in (1,2,5)and np.linalg.norm(local)>.0001):
            raise ValueError('rock_tiger_head_path_disagrees_with_state')
        hurt=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
        if (len(hurt)!=1 or hurt[0]['id']not in binding['head_colliders'] or
                hurt[0]['type']!='CapsuleCollider' or not hurt[0]['active']or not hurt[0]['enabled']or
                hurt[0].get('damage_kind')!='enemy_callback' or hurt[0].get('tag')!='Enemy' or
                hurt[0].get('damage_owner')!=enemy['id']):
            raise ValueError('rock_tiger_original_head_capsule')
        collider=hurt[0]
        if collider['direction']not in (0,1):raise ValueError('rock_tiger_spatial_capsule_axis')
        radius=collider['radius']*scale['x']
        half=max(0.,collider['height']/2-collider['radius'])
        axis=np.eye(2)[collider['direction']]*half
        ends=np.array([xy(collider['local_center'])-axis,xy(collider['local_center'])+axis])
        theta=math.radians(enemy['rotation_z']);origin_angle=math.atan2(direction[1],direction[0])
        # Validate the read-only transform binding against the current native
        # world shape before extrapolating any future rotation or translation.
        rotation=np.array([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
        current=(local+ends)*scale['x']@rotation.T+root
        expected_lo=current.min(axis=0)-radius;expected_hi=current.max(axis=0)+radius
        if max(np.max(abs(xy(collider['center'])-(expected_lo+expected_hi)/2)),
               np.max(abs(xy(collider['extents'])-(expected_hi-expected_lo)/2)))>.0002:
            raise ValueError('rock_tiger_current_capsule_pose_disagrees')
        speed=data['attackSpeed'];maximum=data['maxAttackRange'];aim=data['aimTime']
        if (not all(math.isfinite(v)and v>=0 for v in (speed,maximum,aim,data['activeRange']))
                or not math.isfinite(f['currStateTimeRemain'])or speed<=0):
            raise ValueError('rock_tiger_native_parameter_domain')
        age=observation['state']['time']-f['_lastFixedUpdateTime']
        if not -.0002<=age<=tick+.0002:raise ValueError('rock_tiger_original_fixed_clock')
        age=np.clip(age,0.,tick);steps=np.floor((age+np.asarray(times)+1e-8)/tick).astype(int)
        count=int(max(steps));activation=[None]
        lower=upper=None
        if mode in (1,2):
            if any(not s.startswith('item:')for s in player.unsupported):
                raise ValueError('rock_tiger_player_reference_unsupported')
            if trajectory_states is None:
                _,trajectory_states,valid=player.trajectory(times)
                if not valid:raise ValueError('rock_tiger_player_reference_unsupported')
            actual=observation['role']['fields']['_lastRoleObjPos']
            if (abs(actual['z']-enemy['position']['z'])>1e-5 or abs(f['lookAtOffset']['z'])>1e-5):
                raise ValueError('rock_tiger_spatial_aim_reference')
            query=np.maximum(0.,np.arange(count+1)*tick-age)
            lower,upper=role_reference_rectangles(times,trajectory_states,query,actual)
        if mode==1:
            nearest=np.maximum(lower-root,np.maximum(root-upper,0.))
            farthest=np.maximum(abs(lower-root),abs(upper-root))
            possible=np.flatnonzero(np.linalg.norm(nearest,axis=1)<data['activeRange'])
            certain=np.flatnonzero(np.linalg.norm(farthest,axis=1)<data['activeRange'])
            first=max(1,int(possible[0]))if len(possible)else count+1
            last=max(first,int(certain[0]))if len(certain)else count+1
            if last-first>8:raise ValueError('rock_tiger_activation_uncertainty')
            activation=list(range(first,last+1))
        lows=[];highs=[]
        for trigger in activation:
            state=mode;remaining=np.float32(f['currStateTimeRemain']);position=local.copy()
            angle_lo=angle_hi=theta;lo=[];hi=[]
            for n in range(count+1):
                if n:
                    if state==1 and n>=trigger:
                        state=2;remaining=np.float32(aim)
                    elif state==2:
                        a,b=lower[n]+xy(f['lookAtOffset'])-root,upper[n]+xy(f['lookAtOffset'])-root
                        if np.all(a<=0)and np.all(b>=0):
                            angle_lo,angle_hi=theta-math.pi,theta+math.pi
                        else:
                            corners=np.array([[a[0],a[1]],[a[0],b[1]],[b[0],a[1]],[b[0],b[1]]])
                            angles=np.arctan2(corners[:,1],corners[:,0])-origin_angle
                            middle=math.atan2((a[1]+b[1])/2,(a[0]+b[0])/2)-origin_angle
                            angles=middle+(angles-middle+math.pi)%(2*math.pi)-math.pi
                            angle_lo,angle_hi=float(min(angles)),float(max(angles))
                        remaining=np.float32(remaining-np.float32(tick))
                        if remaining<=0:state=3
                    elif state==3:
                        position=np.float32(position+np.float32(direction*np.float32(np.float32(speed)*np.float32(tick))))
                        if np.linalg.norm(position)>=maximum:state=4
                    elif state==4:
                        if np.linalg.norm(position)<=np.float32(np.float32(speed)*np.float32(tick)):
                            position=np.zeros(2,np.float32);state=5
                        else:
                            position=np.float32(position-np.float32(direction*np.float32(np.float32(speed)*np.float32(tick))))
                bounds=[planar_arc_bounds((position+end)*scale['x'],angle_lo,angle_hi)for end in ends]
                lo.append(np.minimum(bounds[0][0],bounds[1][0])+root-radius)
                hi.append(np.maximum(bounds[0][1],bounds[1][1])+root+radius)
            lows.append(np.array(lo)[steps]);highs.append(np.array(hi)[steps])
        low=np.min(lows,axis=0);high=np.max(highs,axis=0)
        # Fixed-transform stepping does not interpolate the head. Only numeric
        # float32 world/quaternion roundoff needs this guard, not a speed*time
        # interpolation interval that would erase all useful safe windows.
        numeric=abs(float(np.spacing(np.float32(max(abs(root))))))*8+.0001
        geometry={collider['id']:((low+high)/2,(high-low)/2+numeric)}
        zero=np.zeros((len(times),2))
        return (zero,np.zeros(len(times)),
                'EnemyRockTiger.FixedUpdateMovement/AttackLogic/TakeBackLogic; original head capsule and full aim/trigger envelope',
                np.ones(len(times),bool),geometry),None
    except (KeyError,ValueError)as error:
        return None,str(error)


def forecast(enemy, times, observation, player, trajectory_states=None,context=None):
    """Return original root displacement/rotation, or a specific missing rule."""
    from arena_privileged_model import phase, xy
    f, c, kind = enemy['fields'], enemy['custom'], enemy['type']
    zero = np.zeros((len(times), 2))
    angles = np.zeros(len(times))
    source = kind+'.FixedUpdateMovement'
    if kind=='EnemyBrambles':
        path,reason=brambles_path(enemy,times,observation,player,trajectory_states)
        if path is None:return None,reason
        return (zero,angles,'EnemyBrambles.FixedUpdateMovement; original lift/stab owner',np.ones(len(times),bool)),None
    if kind in ('EnemyBramblesSingleThorn','EnemyBrambleCollider'):
        return brambles_child(enemy,times,observation,player,trajectory_states,context)
    if kind=='EnemySuspendSpecial':
        return suspend_special(enemy,times,observation,player)
    if kind=='EnemyConnectElectricBall':
        return connected_electric(enemy,times,observation,player)
    if kind=='EnemyRotateElectricBall':
        return rotating_electric(enemy,times,observation,player)
    if kind in ('EnemyBullutFireRobot','EnemyBullutLaser','EnemyAlarmShooter'):
        if context is not None and 'camera_x'not in context:
            context['camera_x']=camera_x_bounds(observation,times,player,trajectory_states)
        if kind=='EnemyAlarmShooter':
            return alarm_shooter(enemy,times,observation,player,trajectory_states,
                                 context.get('camera_x')if context is not None else None)
        return camera_relative_bullet(enemy,times,observation,player,trajectory_states,
                                      context.get('camera_x')if context is not None else None)
    if kind=='EnemyRockTiger':
        return rock_tiger(enemy,times,observation,player,trajectory_states)
    if kind=='EnemyPiranha':
        return piranha(enemy,times,observation,player,trajectory_states)
    if kind=='EnemyRollingBase':
        return rolling(enemy,times,observation,player,trajectory_states)
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
        path,reason=suspend_path(enemy,times,observation)
        if path is None:return None,reason
        positions,angles=path[:2]
        return (positions-xy(enemy['position']),angles,source),None
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
