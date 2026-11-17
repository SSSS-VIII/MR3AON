"""An already submitted ground air-down survives loss of its finite target."""
from copy import deepcopy
import json,math
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import arena_motion as motion
from arena_vision import Box,Perception,can_air_down,player_future,advance_player
from arena_input_timeline import OwnInputTimeline,freeze_pixels,thaw_pixels


def saved():
    data=json.loads((Path(__file__).parent/'fixtures/arena-ground-down-expired-ack.json').read_text())
    return thaw_pixels(json.dumps(data['planned'])),thaw_pixels(json.dumps(data['receipt'])),data['stamp']


def actor_for(current):
    actor=Perception();actor.visual_role=True;actor.body_height=current['stand_h']/.73
    actor.jump_count=current['jumps'];actor.active_motion=deepcopy(current['motion']);actor.last_observation=current
    return actor


def pending():
    planned,current,stamp=saved();actor=actor_for(current)
    assert can_air_down(planned)and not can_air_down(current)
    actor.action('down',stamp,current,primitive='air_down',source_observation=planned)
    return actor,current,stamp


def test_actual_expired_target_records_the_sent_down_instead_of_prior_jump():
    actor,current,stamp=pending();active=actor.active_motion
    assert active['name']=='air_down'and active['ground_target_missing']
    assert active['contact_pending']and active['requires_contact']and active['support_unconfirmed']
    assert actor.jump_count==current['jumps']==1
    # Finite original pixel target is retained as evidence, never converted
    # into a floor across a gap. No infinity enters the own-input JSON.
    assert active['surface_id']==13
    freeze_pixels(dict(current,motion=active))
    assert math.isinf(motion.duration('air_down',active))


def test_missing_target_never_clamps_or_restores_a_predicted_body():
    actor,current,stamp=pending();active=actor.active_motion;state=dict(current,motion=active)
    assert motion.point('air_down',.2,active)[1]<-active['height']-1
    assert motion.point('air_down',.2,active)[4]==motion.DATA['air_down']['height']
    result=advance_player(state,.3,predict_contact=True)
    assert result['phase']=='flip_down'and result['jumps']==1
    assert result['motion']['ground_target_missing']
    assert not result['ground_contact_observed']and not result['rope_contact_observed']
    assert player_future(state,.2).center[1]>current['player'].center[1]+100


def test_no_valid_submitted_plan_does_not_invent_a_down_motion():
    planned,current,stamp=saved();actor=actor_for(current)
    actor.action('down',stamp,current,primitive='air_down',source_observation=current)
    assert actor.active_motion['name']=='jump1'


def test_timeline_replays_expired_ground_down_once_without_mutating_observed_cursor():
    planned,current,stamp=saved();actor=actor_for(current);line=OwnInputTimeline(actor)
    line.before_observe(current['time']);line.after_observe(current)
    at=stamp+.000001
    event=line.record('down',SimpleNamespace(device_ready_ns=round(at*1e9)),primitive='air_down',planned=planned,input_delay=0.)
    result=line.project(at+.12)
    assert result['replayed_event_ids']==[event.event_id]
    assert result['replayed_events'][0]['resolved_primitive']=='air_down'
    assert result['motion']['ground_target_missing']and result['phase']=='flip_down'
    assert line.consumed==0 and actor.active_motion['name']=='jump1'and actor.jump_count==1


def support(terrain=None):
    return dict(mode='ground',rope=None,terrain=terrain,segments=[],tracking_reference=(0.,0.),rope_segments=[])


def test_observed_new_floor_can_end_missing_target_down_without_clock_prediction():
    actor,current,stamp=pending();s=current['scale_px'];pixels=np.zeros((360,640,3),np.uint8)
    floor=dict(y=293.,at_player=True,samples=[],speed=200.,edge=None,landing=None)
    target=300-.75*s;body=Box(180-current['stand_w']/2,target-current['stand_h']/2,current['stand_w'],current['stand_h'])
    result=actor._finish(pixels,stamp+.2,body,[],support_observation=support(floor))
    assert result['phase']=='ground'and result['jumps']==0 and result['motion']is None
    assert result['ground_contact_observed']


def test_full_body_without_compact_evidence_does_not_erase_uncertain_down():
    actor,current,stamp=pending();pixels=np.zeros((360,640,3),np.uint8);body=Box(172,240,current['stand_w'],current['stand_h'])
    for dt in [.06,.12]:result=actor._finish(pixels,stamp+dt,body,[],support_observation=support())
    assert result['motion']['ground_target_missing']and not result['down_action_end_observed']


def test_actual_compact_then_restored_body_can_acknowledge_short_missed_landing():
    actor,current,stamp=pending();pixels=np.zeros((360,640,3),np.uint8)
    small=Box(176,240,.2*current['scale_px'],.2*current['scale_px'])
    result=actor._finish(pixels,stamp+.06,small,[],support_observation=support())
    assert result['motion']['compact_seen']
    body=Box(172,290,current['stand_w'],current['stand_h'])
    first=actor._finish(pixels,stamp+.1,body,[],support_observation=support())
    assert first['motion']and not first['down_action_end_observed']
    final=actor._finish(pixels,stamp+.15,body,[],support_observation=support())
    assert final['phase']=='air_falling'and final['motion']is None and final['jumps']==0
    assert final['down_action_end_observed']and not final['ground_contact_observed']
