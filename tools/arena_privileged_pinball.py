"""EnemyPinballBase's source-order fixed tick reducer in native coordinates."""
import numpy as np

from arena_privileged_families import native_steps


def forecast(enemy,times,observation,player):
    from arena_privileged_model import phase,xy
    f,c=enemy['fields'],enemy['custom'];mode=phase(f['_enemyState'])
    if mode not in ('none','pinball'):
        return None,'pinball_phase:'+mode
    support=enemy.get('native_support')
    if not support:
        return None,'pinball_native_support_missing'
    a,b=support['start'],support['finish']
    if b['x']<=a['x']:
        return None,'pinball_native_link_support'
    vy=np.float32(f['_currSpeedY']);elapsed=0.
    scale=np.array([enemy['scale'][a] for a in ('x','y','z')],np.float32)
    original=np.array([f['_oriScale'][a] for a in ('x','y','z')],np.float32)
    squeeze,loose=f['_squeeze'],f['_loose'];scale_history=[scale.copy()]
    multiplier=np.float32(1.1)  # original native constant at 0x11b2118
    floor_surface=next((s for s in player.surfaces if s.id==support['id']),None)
    if floor_surface is None:
        from arena_privileged_model import Surface
        floor_surface=Surface(support['id'],a['x'],b['x'],a['y'],
            (b['y']-a['y'])/(b['x']-a['x']),support['is_line'])
    # Keep the original finite ground sequence, with no invisible floor
    # extrapolation across a pit. The native support supplies current identity.
    available=[floor_surface,*player.surfaces]
    end_x=enemy['position']['x']-c['_speedX']*times[-1]
    lo,hi=sorted((end_x,enemy['position']['x']))
    ordered=sorted((s for s in available if s.right>=lo and s.left<=hi),key=lambda s:s.left)
    edge=lo
    for s in ordered:
        if s.left>edge+.01:
            return None,'pinball_future_ground_gap'
        edge=max(edge,s.right)
    if edge<hi-.01:
        return None,'pinball_future_support_missing'
    def update(pos,dt):
        nonlocal mode,vy,elapsed,squeeze,loose,scale
        elapsed+=dt
        if mode=='none':
            if pos[0]<player.initial.x+player.speed*elapsed+18:
                mode='pinball'
            scale_history.append(scale.copy())
            return pos,0.
        # ProcessState calls Squeeze before gravity/rebound. In particular a
        # rebound sets the flag for the *next* tick, and Unity SphereCollider
        # uses the largest scale axis, not the flattened sprite's height.
        if squeeze:
            if abs(scale[0])<abs(np.float32(original[0]*multiplier)):
                scale=np.array([np.float32(scale[0]*multiplier),np.float32(scale[1]/multiplier),original[2]],np.float32)
            else:
                squeeze=False;loose=True
        elif loose:
            if abs(scale[0])>=abs(original[0]):
                scale=np.array([np.float32(scale[0]/multiplier),np.float32(scale[1]*multiplier),original[2]],np.float32)
            else:
                loose=False
        else:
            scale=original.copy()
        ground=next((s for s in available if s.contains(float(pos[0]))),floor_surface)
        floor=np.float32(ground.height(float(pos[0]))+f['_ballRadius'])
        acceleration=c['_acceleratedUp' if vy>0 else '_acceleratedDown']
        vy=np.float32(vy-np.float32(acceleration*dt))
        new_y=np.float32(pos[1]+np.float32(vy*dt))
        if pos[1]>floor and new_y<=floor and vy<0:
            vy=np.float32(c['_reboundSpeedY']);new_y=floor;squeeze=True
        pos[0]=np.float32(pos[0]-np.float32(c['_speedX']*dt));pos[1]=new_y
        scale_history.append(scale.copy())
        return pos,0.
    positions,angles=native_steps(enemy,times,observation,update)
    age=np.clip(observation['state']['time']-f['_lastFixedUpdateTime'],0.,player.tick)
    indices=np.floor((age+times+1e-8)/player.tick).astype(int)
    scales=np.asarray(scale_history)[indices]
    return (positions-xy(enemy['position']),angles,
            'EnemyPinballBase.ProcessState/Squeeze/GroundRebound',None,scales),None
