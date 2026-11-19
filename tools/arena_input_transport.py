"""Delivery limits of FrameServer's existing Android keyboard pulses."""
from math import isfinite
import re

PROFILE = dict(name='android_keyboard_pulses_v1', pulse_ms=80, slide_ms=500,
               release_gap_ms=1000/60)


def check_server_profile(source):
    for name,expected in (('KEY_PULSE_MS',PROFILE['pulse_ms']),('SLIDE_HOLD_MS',PROFILE['slide_ms'])):
        found=re.search(r'\b'+name+r'\s*=\s*(\d+)\s*;',source)
        if not found or int(found[1])!=expected:
            raise ValueError('Android key sender differs from the certified input transport')


def transport_action(action, native_before=''):
    if action == 'down' and native_before.split(':')[0].lower() in ('runonground','slideonground'):
        return 'slide'
    if action not in ('jump','down','slide'):
        raise ValueError('Unknown delivered action')
    return action


def key(action):
    return 'K' if action == 'jump' else 'S'


def minimum_gap(action):
    return (PROFILE['slide_ms'] if action == 'slide' else PROFILE['pulse_ms'])/1000 + PROFILE['release_gap_ms']/1000


def repeat_failure(actions, action, stamp):
    """Do not count a pulse suppressed by held.containsKey as a delivered key."""
    previous = next((a for a in reversed(actions) if key(a['transport_action']) == key(action)), None)
    if previous is None:
        return None
    gap = stamp-previous['input_time']
    required = minimum_gap(previous['transport_action'])
    if not isfinite(gap) or gap < required-.00002:
        return dict(reason='input_transport_repeat_too_close', previous_event=previous['index'],
                    transport_action=action, gap_ms=gap*1000, minimum_gap_ms=required*1000)
    return None
