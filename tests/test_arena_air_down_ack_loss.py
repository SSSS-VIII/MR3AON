"""A real emitted down input must survive a one-image rope detection gap."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_input_timeline import OwnInputTimeline
from arena_vision import Box,Perception,can_air_down,transition_speed

DATA=json.loads((Path(__file__).parent/'fixtures/arena-air-down-ack-rope-loss.json').read_text())


def pixels(value):
    result=deepcopy(value);result['player']=Box(**result['player']);result['tracks']=[]
    return result


def replay():
    state=pixels(DATA['before']);actor=Perception();actor.visual_role=True
    actor.jump_count=state['jumps'];actor.active_motion=deepcopy(state['motion'])
    actor.last_action=state['motion']['started']
    actor.motion_origin=dict(scale=state['scale_px'],stand_w=state['stand_w'],stand_h=state['stand_h'])
    line=OwnInputTimeline(actor);line.before_observe(state['time']);line.after_observe(state)
    event=DATA['event'];planned=pixels(DATA['planned'])
    assert can_air_down(planned)and not can_air_down(state)
    line.record('down',SimpleNamespace(device_ready_ns=round(event['enqueued_time']*1e9)),
                primitive='air_down',planned=planned)
    return actor,line


def observe(line,item,*,predicted=False):
    state=pixels(item['pixels']);actor=line.perception
    support=dict(mode='rope',rope=state['rope'],terrain=None,
        rope_segment=state['rope_segment'],rope_segments=state['rope_segments'],
        segments=state['visible_supports'],tracking_reference=(0.,state['camera_reference_y']))
    def observer(image,stamp):
        result=actor._finish(image,stamp,state['player'],[],support_observation=support,
                             player_observed=not predicted)
        return dict(result,player_predicted=predicted)
    return line.observe(np.zeros((360,640,3),np.uint8),state['time'],observer=observer)


def test_recorded_down_is_not_replayed_as_an_old_double_jump_after_rope_loss():
    actor,line=replay();future=line.project(DATA['after'][0]['pixels']['time'])
    assert future['replayed_events'][0]['resolved_primitive']=='air_down'
    assert future['motion']['support_unconfirmed']and future['motion']['requires_contact']
    assert transition_speed(future['motion'])==28. and future['jumps']==2
    # A stale reference is not a certified rope, even beyond predicted contact.
    later=line.project(DATA['before']['time']+.8,predict_contact=True)
    assert later['jumps']==2 and later['motion']is not None


def test_real_restored_body_below_rope_ends_transfer_and_replenishes_jumps():
    actor,line=replay();states=[observe(line,item)for item in DATA['after'][:4]]
    assert states[0]['motion']['name']=='air_down'and states[0]['jumps']==2
    assert states[-1]['phase']=='rope_below'and states[-1]['rope_contact_observed']
    assert states[-1]['jumps']==0 and states[-1]['motion']is None
    future=line.project(states[-1]['time']+.04)
    assert future['player'].center[1]>future['rope']


def test_predicted_contact_cannot_confirm_the_missing_rope_target():
    actor,line=replay()
    for item in DATA['after'][:4]:state=observe(line,item,predicted=True)
    assert state['jumps']==2 and not state['rope_contact_observed']
    assert state['motion']['requires_contact']
    actual=observe(line,DATA['after'][4])
    assert actual['phase']=='rope_below'and actual['jumps']==0


def test_unplanned_or_invalid_down_does_not_invent_a_transfer():
    actor,line=replay();missing=pixels(DATA['before'])
    actor.action('down',missing['time'],missing,primitive=None,source_observation=pixels(DATA['planned']))
    assert actor.active_motion['name']=='jump2'
    actor.action('down',missing['time'],missing,primitive='air_down',source_observation=missing)
    assert actor.active_motion['name']=='jump2'
