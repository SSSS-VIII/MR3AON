"""Original stationary poleaxe state and fixed-tick Spine damage envelopes.

No engine trials or visual estimates. A one-fixed-update ordering interval is
kept explicitly; unsupported mixing, pooling residue and callbacks are rejected.
"""
from functools import lru_cache
import json
import math
from pathlib import Path

import numpy as np
from arena_spine_geometry import full_scale_follow_quad

PROFILE=Path(__file__).with_name('arena_privileged_poleaxe_poses.json')


@lru_cache(maxsize=1)
def profile():
    data=json.loads(PROFILE.read_text())
    if (data['schema']!=1 or data['asset_name']!='axewarrior.skel' or data['skin']!='1'
            or data['skeleton_version']!='4.0.21' or data['runtime_version']!='4.0.31'
            or data['skeleton_sha256']!='b810503ba632426fd56d99347192ed4efaade91a0810b09ce53b44fd5158f6ba'):
        raise ValueError('poleaxe_pose_source')
    chain=data['skeleton_bones']
    if ([b['name']for b in chain]!=['root','axe2','axe'] or any(
            b['transform_mode']!=0 or b['shear_x'] or b['shear_y'] for b in chain)):
        raise ValueError('poleaxe_pose_transform_chain')
    return data



def bone_matrix(bone):
    return np.array([[bone['a'],bone['b']],[bone['c'],bone['d']]])


def adjusted_bone(sample,ratio):
    if ratio==(1.,1.):return sample['bone']
    parent=next(b for b in sample['bones']if b['name']=='axe2');bone=sample['bone']
    parent_matrix=bone_matrix(parent)
    correction=parent_matrix@np.diag(ratio)@np.linalg.inv(parent_matrix)
    matrix=correction@bone_matrix(bone)
    position=np.array([parent['x'],parent['y']])+correction@np.array([bone['x']-parent['x'],bone['y']-parent['y']])
    return dict(name='axe',x=position[0],y=position[1],a=matrix[0,0],b=matrix[0,1],c=matrix[1,0],d=matrix[1,1])


def carry_ratio(spine,clip,index):
    properties=clip['keyed_properties']['axe2']
    if 'ScaleTimeline' in properties:return (1.,1.)
    if properties!=['RotateTimeline','TranslateTimeline']:
        raise ValueError('poleaxe_unmapped_unkeyed_property')
    # Down-ready does not key axe2 scale. A pooled enemy keeps that local
    # scale from its preceding attack; all other ancestor properties are
    # keyed. Recover the signed local scale ratios from the original posed
    # parent matrices, retaining rather than resetting those native values.
    sample=clip['samples'][min(index,len(clip['samples'])-1)]
    native={b['name']:b for b in spine['bones']};cached={b['name']:b for b in sample['bones']}
    for name in ('root','axe2'):
        if max(abs(native[name][k]-cached[name][k])for k in ('x','y'))>.0002:
            raise ValueError('poleaxe_parent_pose_disagrees_with_cache')
    if max(abs(native['root'][k]-cached['root'][k])for k in ('a','b','c','d'))>.0002:
        raise ValueError('poleaxe_parent_pose_disagrees_with_cache')
    local= np.linalg.solve(bone_matrix(cached['root']),bone_matrix(cached['axe2']))
    actual=np.linalg.solve(bone_matrix(native['root']),bone_matrix(native['axe2']))
    ratio=np.sum(local*actual,axis=0)/np.sum(local*local,axis=0)
    if not np.isfinite(ratio).all() or np.max(abs(local*ratio-actual))>.0002:
        raise ValueError('poleaxe_parent_scale_not_a_native_retained_scale')
    return tuple(float(v)for v in ratio)


def checked_entry(enemy):
    data=profile();spine=enemy.get('spine',{})
    if (not spine.get('initialized') or spine.get('tracks_truncated') or spine.get('bones_truncated')
            or spine.get('asset_name')!=data['asset_name'] or spine.get('skin')!=data['skin']
            or abs(spine.get('asset_fields',{}).get('scale',0)-data['scale'])>1e-9):
        raise ValueError('poleaxe_original_spine_missing')
    if (spine.get('time_scale')!=1 or spine.get('state_fields',{}).get('timeScale')!=1
            or spine.get('state_callbacks')!={}):
        raise ValueError('poleaxe_spine_clock_or_callbacks')
    if any(spine.get('fields',{}).get(k)!=v for k,v in dict(x=0,y=0,scaleX=1,scaleY=1).items()):
        raise ValueError('poleaxe_skeleton_transform')
    tracks=spine['tracks']
    if len(tracks)!=1 or tracks[0]['index']!=0 or not tracks[0].get('entry'):
        raise ValueError('poleaxe_multiple_or_missing_tracks')
    entry=tracks[0]['entry'];clip=data['animations'].get(entry.get('animation'))
    if clip is None:raise ValueError('poleaxe_unknown_animation')
    if (entry.get('alpha')!=1 or entry.get('timeScale')!=1 or entry.get('reverse') is not False
            or entry.get('loop') is not False or entry.get('mixDuration')!=0
            or entry.get('mixing_from') or entry.get('has_next') is not False
            or entry.get('callbacks')!={} or entry.get('animationStart')!=0
            or abs(entry.get('animationEnd',0)-clip['duration'])>1e-6 or entry.get('delay')!=0):
        raise ValueError('poleaxe_mixed_queued_or_modified_track')
    t=entry['trackTime'];tick=data['tick'];index=round(t/tick)
    if t<0 or abs(t-index*tick)>5e-5:
        raise ValueError('poleaxe_track_not_on_native_fixed_lattice')
    bone=next((b for b in spine['bones']if b['name']=='axe'),None)
    ratio=carry_ratio(spine,clip,index)
    cached=adjusted_bone(clip['samples'][min(index,len(clip['samples'])-1)],ratio)
    if bone is None or max(abs(bone[k]-cached[k]) for k in ('x','y','a','b','c','d'))>.0002:
        raise ValueError('poleaxe_current_pose_disagrees_with_cache')
    return data,spine,entry,index



@lru_cache(maxsize=128)
def posed_clips(basis_values,origin_values,local_values,ratio):
    basis=np.asarray(basis_values).reshape(2,2);origin=np.asarray(origin_values)
    cx,cy,sx,sy=local_values
    local=np.array([[cx-sx,cy-sy],[cx+sx,cy-sy],[cx+sx,cy+sy],[cx-sx,cy+sy]])
    output={}
    for name,clip in profile()['animations'].items():
        bones=[adjusted_bone(s,ratio)if name=='attack_down_ready'else s['bone']for s in clip['samples']]
        matrices=np.array([[[b['a'],b['b']],[b['c'],b['d']]]for b in bones])
        offsets=np.array([[b['x'],b['y']]for b in bones])
        output[name]=(np.einsum('nij,kj->nki',matrices,local)+offsets[:,None,:])@basis.T+origin
    return output


def forecast(enemy,times,observation,player,trajectory_states=None):
    from arena_privileged_model import phase,rows,xy
    try:
        data,spine,entry,initial_index=checked_entry(enemy)
        tick=observation['state']['fixedDeltaTime']
        if abs(tick-data['tick'])>1e-8:raise ValueError('poleaxe_fixed_clock')
        f=enemy['fields'];position=xy(enemy['position'])
        if any(np.linalg.norm(xy(f[k])-position)>1e-5 for k in ('_lastPosition','_secondLastPosition')):
            raise ValueError('poleaxe_moving_root')
        if np.linalg.norm(xy(f['currMoveVelocity']))>1e-6:raise ValueError('poleaxe_moving_root')
        mode=phase(f['_enemyState']);direction=enemy['custom']['_attackDir']
        suffix={'Downward: 0':'down','Upward: 1':'up'}.get(direction)
        if suffix is None or mode not in ('idle','attack'):raise ValueError('poleaxe_phase_or_direction')
        ready='attack_'+suffix+'_ready';attack='attack_'+suffix
        if entry['animation']!=(ready if mode=='idle' else attack):raise ValueError('poleaxe_track_phase_disagreement')
        age=np.clip(observation['state']['time']-f['_lastFixedUpdateTime'],0,tick)
        steps=np.floor((age+np.asarray(times)+1e-8)/tick).astype(int)
        colliders=[c for c in rows(enemy['colliders'])if c.get('damage_kind')]
        if len(colliders)!=2:raise ValueError('poleaxe_original_damage_shapes')
        weapon=next((c for c in colliders if c.get('spine_follow')),None)
        body=next((c for c in colliders if not c.get('spine_follow')),None)
        if weapon is None or body is None or body['type']!='BoxCollider':raise ValueError('poleaxe_damage_shape_binding')
        # Validate the whole original follower chain before using any pose.
        full_scale_follow_quad(spine,next(b for b in spine['bones']if b['name']=='axe'),weapon)
        native_direction=observation.get('camera',{}).get('direction')
        if native_direction not in (-1,1):raise ValueError('poleaxe_original_run_direction')
        launch_lo=launch_hi=math.inf
        if mode=='idle':
            if player.unsupported:raise ValueError('poleaxe_player_trajectory_unsupported')
            # The original threshold reads RoleObj (physics root plus parent
            # offset). Enemy/player update order can see either endpoint of
            # that fixed update; keep both until the threshold is certain.
            bounds=np.r_[0.,np.maximum(0.,np.arange(1,max(steps)+2)*tick-age)]
            # Candidate actions can change slope speed and parent offsets.
            # Their trajectory is supplied by the controller at its own mesh.
            if trajectory_states is not None:
                xs=np.asarray([m.physical_x+m.offset_render for m in trajectory_states])
                previous=np.asarray([m.previous_x+m.offset_render for m in trajectory_states])
                lo=np.interp(bounds,times,np.minimum(xs,previous));hi=np.interp(bounds,times,np.maximum(xs,previous))
            else:
                _,motors,_=player.trajectory(bounds)
                lo=np.array([min(m.physical_x,m.previous_x)+m.offset_render for m in motors])
                hi=np.array([max(m.physical_x,m.previous_x)+m.offset_render for m in motors])
            near=position[0]-np.stack((lo,hi),axis=1)
            near*=native_direction
            possible=np.flatnonzero(near.min(axis=1)<=enemy['custom']['_attackDisNinja'])
            certain=np.flatnonzero(near.max(axis=1)<=enemy['custom']['_attackDisNinja'])
            if len(possible):launch_lo=max(1,int(possible[0])-1)
            if len(certain):launch_hi=max(launch_lo,int(certain[0])+1)
        basis=np.column_stack((xy(spine['axis_x']),xy(spine['axis_y'])))
        clips=posed_clips(tuple(basis.ravel()),tuple(xy(spine['origin'])),
            (weapon['local_center']['x'],weapon['local_center']['y'],weapon['size']['x']/2,weapon['size']['y']/2),
            carry_ratio(spine,data['animations'][entry['animation']],initial_index))
        lows=[];highs=[]
        for n in steps:
            if n==0:
                poses=[np.array([xy(p) for p in weapon['quad']])]
            elif mode=='attack':
                q=clips[attack];poses=[q[min(initial_index+n+d,len(q)-1)]for d in (-1,0,1)]
            else:
                q=clips[ready];poses=[]
                if n<=launch_hi:poses.append(q[min(initial_index+n,len(q)-1)])
                if n>=launch_lo:
                    q=clips[attack]
                    first=int(launch_lo);last=min(n,int(launch_hi)if math.isfinite(launch_hi)else n)
                    for launch in range(first,last+1):
                        for order in (0,1):poses.append(q[min(max(0,n-launch+order),len(q)-1)])
            points=np.concatenate(poses);lows.append(points.min(axis=0));highs.append(points.max(axis=0))
        # Native world transforms accumulate float32 operations at the world
        # origin; retain rounding plus the admitted cached-bone residual.
        local_x=abs(weapon['local_center']['x'])+weapon['size']['x']/2
        local_y=abs(weapon['local_center']['y'])+weapon['size']['y']/2
        numeric=(8*max(abs(float(np.spacing(np.float32(v))))for v in xy(spine['origin']))
                 +.0002*(1+local_x+local_y)*math.sqrt(2)*np.linalg.norm(basis,ord=2))
        lo=np.asarray(lows)-numeric;hi=np.asarray(highs)+numeric
        geometry={weapon['id']:((lo+hi)/2,(hi-lo)/2),
                  body['id']:(np.tile(xy(body['center']),(len(times),1)),np.tile(xy(body['extents']),(len(times),1)))}
        zero=np.zeros((len(times),2));angles=np.zeros(len(times))
        return (zero,angles,'EnemyPoleaxeWarrior.FixedUpdateMovement/SetEnemyState; original fixed-tick Spine poses and update-order envelope',
                np.ones(len(times),bool),geometry),None
    except (ValueError,KeyError,StopIteration)as error:
        return None,str(error)
