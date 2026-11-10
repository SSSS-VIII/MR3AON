"""Measured original-client action/collider priors; no board or game-state input."""
from bisect import bisect_right
import json
from pathlib import Path

DATA=json.loads((Path(__file__).resolve().parents[1]/'arena/vision-motion-priors.json').read_text())
TIMES={name:tuple(p[0]for p in profile['points'])for name,profile in DATA['profiles'].items()}


def is_rope_transition(name):
    return name.startswith('rope') or name=='air_down'


def duration(name,parameters=None):
    if name=='air_down':
        prior=DATA['air_down']
        speed=prior['speed']-parameters.get('surface_velocity',0.)
        return max(0,parameters['height']+parameters['lead']+prior['speed']*prior['input_delay'])/max(.001,speed)+prior['settle_seconds']
    profile=DATA['profiles'][name]
    return profile.get('duration',profile['points'][-1][0])


def point(name,t,parameters=None):
    """Return collider offsetX, root displacementY, offsetY, width, height."""
    if name=='air_down':
        prior=DATA['air_down'];delay=prior['input_delay']
        if t<=0:
            return [parameters['offset_x'],0.,parameters['offset_y'],parameters['width'],parameters['height_box']]
        delta=parameters['lead']*min(1,t/delay)-prior['speed']*max(0,t-delay)
        target=-parameters['height']-parameters.get('surface_velocity',0.)*t
        arrived=delta<=target
        return [DATA['stand_offset_x']if arrived else 0.,max(target,delta),0.,
                prior['stand_width']if arrived else prior['width'],
                DATA['stand_height']if arrived else prior['height']]
    profile=DATA['profiles'][name]
    points=profile['points']
    if t<=0:
        return points[0][1:]
    if t>=points[-1][0]:
        value=points[-1][1:].copy()
        dt=t-points[-1][0]
        if 'tail_velocity' in profile:
            value[1]+=profile['tail_velocity']*dt+.5*profile['tail_acceleration']*dt*dt
        return value
    index=bisect_right(TIMES[name],t)
    a,b=points[index-1],points[index]
    f=(t-a[0])/(b[0]-a[0])
    return [x+(y-x)*f for x,y in zip(a[1:],b[1:])]


def phase(name,t,parameters=None):
    if is_rope_transition(name):
        below=name in ('rope_down','air_down')
        if t<duration(name,parameters):
            return 'flip_down' if below else 'flip_up'
        if name=='air_down'and parameters.get('destination')=='ground':return 'ground'
        return 'rope_below' if below else 'rope_above'
    return name+('_rising' if t<DATA['profiles'][name]['apex'] else '_falling')
