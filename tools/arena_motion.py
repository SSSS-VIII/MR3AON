"""Measured original-client action/collider priors; no board or game-state input."""
from bisect import bisect_right
import json
from pathlib import Path

DATA=json.loads((Path(__file__).resolve().parents[1]/'arena/vision-motion-priors.json').read_text())
TIMES={name:tuple(p[0]for p in profile['points'])for name,profile in DATA['profiles'].items()}


def is_ground_transition(name):
    return name in ('slide','ground_recovery')


def recovery_factor(t):
    prior=DATA['profiles']['slide']
    return prior['recovery_multiplier']**(max(0,t)/prior['recovery_tick_seconds'])


def root_extra(name,t,parameters=None):
    """Measured root advance, independent of the moving hurt-collider offset."""
    if name!='slide':return 0.
    profile=DATA['profiles']['slide'];points=profile['root_extra_x']
    factor=(parameters or{}).get('base_speed',profile['reference_speed'])/profile['reference_speed']
    if t<=0:return 0.
    if t>=points[-1][0]:return points[-1][1]*factor
    index=bisect_right([p[0]for p in points],t)
    a,b=points[index-1],points[index];f=(t-a[0])/(b[0]-a[0])
    return (a[1]+(b[1]-a[1])*f)*factor


def root_extra_velocity(name,t,parameters=None):
    if t<=0:return 0.
    # Symmetric secant also smooths the one-physics-tick capture alignment.
    a=max(0,t-.025);b=t+.025
    return (root_extra(name,b,parameters)-root_extra(name,a,parameters))/(b-a)


def is_rope_transition(name):
    return name.startswith('rope') or name in ('air_down','air_up')


def transfer_delay(name,parameters=None):
    return (parameters or{}).get('input_delay',DATA['air_up'if name=='air_up'else'air_down']['input_delay'])


def duration(name,parameters=None):
    if name=='ground_recovery':return 5.
    if name=='air_up':
        # EnterRollToLineOn descends at 28 above the upper rope contact,
        # but ascends at 8 when entered below it. This is not a fixed flip.
        speed=parameters['speed']-parameters.get('surface_velocity',0.)
        distance=parameters['height']+parameters['lead']+parameters['speed']*transfer_delay(name,parameters)
        return max(0,distance/speed)+DATA['air_down']['settle_seconds'] if abs(speed)>1e-6 else float('inf')
    if name=='air_down':
        prior=DATA['air_down']
        speed=parameters.get('speed',prior['speed'])
        relative=speed-parameters.get('surface_velocity',0.)
        return max(0,parameters['height']+parameters['lead']+speed*transfer_delay(name,parameters))/max(.001,relative)+prior['settle_seconds']
    profile=DATA['profiles'][name]
    return profile.get('duration',profile['points'][-1][0])


def point(name,t,parameters=None):
    """Return collider offsetX, root displacementY, offsetY, width, height."""
    parameters=parameters or{}
    if name=='ground_recovery':
        return [DATA['stand_offset_x']+parameters['offset_carry_x']*recovery_factor(t),0.,0.,.4,DATA['stand_height']]
    if name in ('air_down','air_up'):
        prior=DATA['air_down'];delay=transfer_delay(name,parameters)
        if t<=0:
            return [parameters['offset_x'],0.,parameters['offset_y'],parameters['width'],parameters['height_box']]
        speed=parameters.get('speed',prior['speed'])
        delta=parameters['lead']*min(1,t/delay)-speed*max(0,t-delay)
        target=-parameters['height']-parameters.get('surface_velocity',0.)*t
        arrived=t>=delay and (delta<=target if speed>0 else delta>=target)
        # The original physics collider is restored before the rendered root
        # finishes interpolating to the rope. Preserve that larger hurt body.
        restored=arrived or (name=='air_up'and t>=delay and
                            abs(delta-target)<=abs(speed)*DATA['air_up']['collider_restore_lead'])
        return [DATA['stand_offset_x']if restored else 0.,target if arrived else delta,0.,
                prior['stand_width']if restored else prior['width'],
                DATA['stand_height']if restored else prior['height']]
    profile=DATA['profiles'][name]
    points=profile['points']
    if t<=0:
        value=points[0][1:].copy();value[0]+=parameters.get('offset_carry_x',0.)
        return value
    if t>=points[-1][0]:
        value=points[-1][1:].copy()
        dt=t-points[-1][0]
        if name=='slide':
            value[0]=DATA['stand_offset_x']+(value[0]-DATA['stand_offset_x'])*recovery_factor(dt)
        if 'tail_velocity' in profile:
            value[1]+=profile['tail_velocity']*dt+.5*profile['tail_acceleration']*dt*dt
    else:
        index=bisect_right(TIMES[name],t)
        a,b=points[index-1],points[index]
        f=(t-a[0])/(b[0]-a[0])
        value=[x+(y-x)*f for x,y in zip(a[1:],b[1:])]
    carry=parameters.get('offset_carry_x',0.)
    if name=='slide':
        # A new slide can begin before the previous parent offset has settled.
        end=points[-1][0]
        value[0]+=carry*profile['slide_multiplier']**(min(t,end)/.01)*recovery_factor(max(0,t-end))
    else:value[0]+=carry  # The original parent offset freezes while airborne.
    return value


def phase(name,t,parameters=None):
    if is_ground_transition(name):
        return 'slide'if name=='slide'and t<duration(name)else'ground'
    if is_rope_transition(name)and (parameters or{}).get('contact_pending'):
        return 'flip_up'if name in ('air_up','rope_up')else'flip_down'
    if is_rope_transition(name):
        below=name in ('rope_down','air_down')
        if t<duration(name,parameters):
            return 'flip_down' if below else 'flip_up'
        if name=='air_down'and parameters.get('destination')=='ground':return 'ground'
        return 'rope_below' if below else 'rope_above'
    return name+('_rising' if t<DATA['profiles'][name]['apex'] else '_falling')
