"""Measured original-client action/collider priors; no board or game-state input."""
from bisect import bisect_right
import json
from pathlib import Path

DATA=json.loads((Path(__file__).resolve().parents[1]/'arena/vision-motion-priors.json').read_text())
TIMES={name:tuple(p[0]for p in profile['points'])for name,profile in DATA['profiles'].items()}


def duration(name):
    profile=DATA['profiles'][name]
    return profile.get('duration',profile['points'][-1][0])


def point(name,t):
    """Return collider offsetX, root displacementY, offsetY, width, height."""
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


def phase(name,t):
    if name.startswith('rope'):
        if t<duration(name):
            return 'flip_down' if name=='rope_down' else 'flip_up'
        return 'rope_below' if name=='rope_down' else 'rope_above'
    return name+('_rising' if t<DATA['profiles'][name]['apex'] else '_falling')
