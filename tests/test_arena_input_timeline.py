from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_input_timeline import OwnInputTimeline,ActionCursor,advance
from arena_action_timing import commit_action
from arena_vision import Box,Perception,advance_player,serializable
from arena_mpc import start_action


def standing(stamp=1.):
    return dict(time=stamp,player=Box(172.,211.28,16.,37.44),phase='rope_above',jumps=0,
        motion=None,rope=260.,terrain=None,scale_px=40.,stand_w=16.,stand_h=37.44,
        vy=0.,vx=0.,tracks=[],rope_contact_observed=True,ground_contact_observed=False,
        camera_reference_y=260.,camera_velocity_y=0.)


def falling():
    state=standing();state.update(player=Box(176.,176.,8.,8.),phase='flip_down',jumps=2,
        motion=dict(name='air_down',started=.9,height=5.55,lead=0.,offset_x=0.,offset_y=0.,
        width=.2,height_box=.2,destination='rope',requires_contact=True),rope_contact_observed=False)
    return state


def seed(state=None):
    state=deepcopy(state or standing());actor=Perception();actor.visual_role=True;actor.body_height=37.44/.73
    actor.jump_count=state['jumps'];actor.active_motion=deepcopy(state['motion'])
    actor.motion_origin=dict(x=state['player'].center[0],y=state['player'].center[1]-260.,scale=40.,stand_w=16.,stand_h=37.44)
    actor.last_observation=state
    line=OwnInputTimeline(actor);line.before_observe(state['time']);line.after_observe(state)
    return actor,line


def key(line,action,at,primitive=None,planned=None):
    return line.record(action,SimpleNamespace(device_ready_ns=round(at*1e9)),primitive=primitive,planned=planned,input_delay=0.)


def observe_body(line,at,body=None,*,observed=True,ground=False):
    actor=line.perception;body=body or standing()['player']
    support=dict(mode='ground'if ground else'rope',rope=None if ground else 260.,
                 terrain=dict(y=253.,at_player=True,samples=[],speed=300.,edge=None,landing=None)if ground else None,
                 segments=[],tracking_reference=(0.,0.),rope_segments=[])
    def observer(image,stamp):
        result=actor._finish(image,stamp,body,[],support_observation=support,player_observed=observed)
        result.update(scale_px=40.,stand_w=16.,stand_h=37.44,player_predicted=not observed)
        return result
    return line.observe(np.zeros((360,640,3),np.uint8),at,capture_return_stamp=at+.03,observer=observer)


def action_state(actor):
    return deepcopy({key:getattr(actor,key)for key in ('active_motion','motion_origin','jump_count','last_action','last_flip')})


def test_ack_does_not_retroactively_move_observed_cursor_and_prior_pixels_stay_prior():
    actor,line=seed();event=key(line,'jump',1.1,'jump1');original=action_state(actor)
    assert actor.active_motion is None and actor.jump_count==0
    seen=observe_body(line,1.05)
    assert seen['phase']=='rope_above'and seen['jumps']==0 and line.consumed==0
    future=line.project(1.15)
    assert future['motion']['name']=='jump1'and future['jumps']==1
    assert future['replayed_event_ids']==[event.event_id]
    assert action_state(actor)==original and line.latest['motion']is None
    assert seen['image_stamp']==1.05 and seen['capture_return_stamp']==1.08


def test_consumption_happens_before_any_observation_and_only_once():
    actor,line=seed();key(line,'jump',1.1,'jump1');future=line.project(1.12);seen=[]
    def observer(image,at):
        seen.append(action_state(actor));return dict(future,time=at,player_predicted=True)
    line.observe(None,1.12,observer=observer)
    assert seen[0]['active_motion']['name']=='jump1'and seen[0]['jump_count']==1
    assert line.consumed==1
    a=line.project(1.15);b=line.project(1.15)
    assert a['jumps']==b['jumps']==1 and a['replayed_event_ids']==b['replayed_event_ids']==[]


def test_two_then_three_events_without_images_use_each_intermediate_state():
    actor,line=seed();key(line,'jump',1.1,'jump1');key(line,'down',1.2,'air_down')
    current=line.project(1.23)
    assert current['motion']['name']=='air_down'and current['jumps']==1
    key(line,'jump',1.25,'air_up',current)
    current=line.project(1.27)
    assert current['motion']['name']=='air_up'and current['jumps']==1
    assert [r['resolved_primitive']for r in current['replayed_events']]==['jump1','air_down','air_up']
    assert line.consumed==0 and actor.jump_count==0 and actor.active_motion is None
    partial=line.project(1.15)
    assert partial['motion']['name']=='jump1'and partial['replayed_event_ids']==[1]


def test_old_landing_frame_does_not_erase_a_later_already_submitted_jump():
    state=falling();state.update(phase='flip_up',motion=dict(state['motion'],name='air_up',height=2.,speed=28.))
    actor,line=seed(state);key(line,'jump',1.1,'jump1',standing(1.1))
    old=observe_body(line,1.05)
    assert old['rope_contact_observed']and old['jumps']==0
    current=line.project(1.15)
    assert current['jumps']==1 and current['motion']['name']=='jump1'
    assert actor.jump_count==0 and line.consumed==0


def test_predicted_contact_never_clears_observed_jump_ledger():
    state=start_action(standing(),'jump2');state['jumps']=2
    actor,line=seed(state)
    observed=line.project(2.5)
    assert observed['jumps']==2 and observed['motion']['name']=='jump2'
    assert observed['contact_unconfirmed']and not observed.get('rope_contact_observed')
    forecast=line.project(2.5,predict_contact=True)
    assert forecast['jumps']==0 and forecast['phase']=='rope_above'
    assert actor.jump_count==2 and actor.active_motion['name']=='jump2'


def test_predicted_landing_then_key_keeps_real_ledger_and_marks_uncertainty():
    state=start_action(standing(),'jump2');state['jumps']=2
    actor,line=seed(state);key(line,'jump',2.5,'jump1',standing(2.5))
    line.before_observe(2.6)
    assert actor.jump_count==2 and line.last_receipts[0]['contact_unconfirmed']
    assert line.last_receipts[0]['primitive']=='jump1'
    # A generated/planned ground pose is not permission to rewrite truth.
    fake=dict(standing(2.6),rope_contact_observed=False,jumps=0,motion=None,player_predicted=True)
    actor.jump_count=0;actor.active_motion=None
    result=line.after_observe(fake)
    assert result['jumps']==2 and result['contact_unconfirmed']


def test_contact_flags_on_forecast_are_always_false_and_no_planned_markers_leak():
    actor,line=seed();state=line.project(1.05)
    assert not state['rope_contact_observed']and not state['ground_contact_observed']
    assert line.latest['rope_contact_observed']


def test_boundary_equal_consumes_once_and_equal_time_events_keep_ack_order():
    actor,line=seed();key(line,'jump',1.1,'jump1');key(line,'down',1.1,'air_down')
    state=line.project(1.1)
    assert state['replayed_event_ids']==[1,2]
    assert state['motion']['name']=='air_down'
    line.before_observe(1.1)
    assert line.consumed==2 and actor.active_motion['name']=='air_down'
    line.after_observe(state)
    assert line.project(1.2)['replayed_event_ids']==[]


@pytest.mark.parametrize('reverse',[False,True])
def test_ack_support_loss_keeps_recovery_intent_and_spent_jumps(reverse):
    state=falling();rope=dict(id=1,kind='rope',a=(0.,260.),b=(185.,260.),vx=-300.,vy=0.)
    state.update(rope_segment=rope,rope_segments=[rope])
    if reverse:
        state.update(phase='flip_up',player=Box(176.,256.,8.,8.),motion=dict(name='air_up',started=.9,
            height=-1.5,lead=0.,speed=-8.,offset_x=0.,offset_y=0.,width=.2,height_box=.2,
            destination='rope',requires_contact=True))
    actor,line=seed(state)
    key(line,'down'if reverse else'jump',1.066,'air_down'if reverse else'air_up',state)
    future=line.project(1.08)
    assert future['jumps']==2 and future['motion']['name']==('air_down'if reverse else'air_up')
    assert future['motion']['support_unconfirmed']and future['motion']['requires_contact']
    line.before_observe(1.08)
    assert actor.jump_count==2 and actor.active_motion['support_unconfirmed']
    line.after_observe(future)
    inferred=observe_body(line,1.4,ground=True,observed=False)
    assert inferred['jumps']==2
    actual=observe_body(line,1.45,ground=True)
    assert actual['ground_contact_observed']and actual['jumps']==0


def test_slide_is_consumed_before_support_prefix_and_preserves_jump_carry():
    initial=standing();initial.update(phase='ground',rope=None,rope_contact_observed=False,ground_contact_observed=True,
        terrain=dict(y=253.,at_player=True,samples=[],speed=300.,edge=None,landing=None))
    actor,line=seed(initial);key(line,'slide',1.1,'slide');sliding=line.project(1.2)
    key(line,'jump',1.22,'jump1',sliding)
    current=line.project(1.24)
    assert current['motion']['name']=='jump1'and current['motion']['offset_carry_x']>0
    observed=[]
    def observer(image,at):
        observed.append(actor.active_motion['name']);return dict(sliding,time=at,player_predicted=True)
    line.observe(None,1.2,observer=observer)
    assert observed==['slide']and line.consumed==1


def test_duplicate_crc_projects_without_consuming_or_touching_cursor_or_history():
    actor,line=seed();key(line,'jump',1.1,'jump1');before=action_state(actor);obs=serializable(deepcopy(line.latest))
    high=line.project(1.4);low=line.project(1.15);again=line.project(1.4)
    assert serializable(high)==serializable(again)
    assert low['jumps']==high['jumps']==1 and line.consumed==0
    assert action_state(actor)==before and serializable(line.latest)==obs
    assert actor.tracker is line.perception.tracker


def test_zero_age_consumed_action_reuses_original_ack_transition_exactly():
    actor,line=seed();legacy=Perception();legacy.visual_role=True
    ack=SimpleNamespace(device_ready_ns=1_100_000_000)
    report=commit_action(legacy,standing(),'jump',ack)
    event=line.record('jump',ack)
    assert event.estimated_consumption==report['committed_time']
    line.before_observe(event.estimated_consumption)
    assert actor.active_motion==legacy.active_motion and actor.motion_origin==legacy.motion_origin
    assert actor.jump_count==legacy.jump_count


def test_no_event_projection_matches_existing_short_motion_geometry():
    initial=start_action(standing(),'jump1');actor,line=seed(initial)
    actual=line.project(1.15);expected=advance_player(initial,.15)
    assert vars(actual['player'])==pytest.approx(vars(expected['player']))
    assert actual['motion']==expected['motion']and actual['phase']==expected['phase']


def test_mutable_caller_and_event_readers_cannot_modify_saved_pixel_target():
    actor,line=seed();planned=falling();planned.update(native={'root':999},health=5000)
    event=key(line,'jump',1.1,'air_up',planned)
    planned['motion']['height']=999;planned['player'].y=999
    read=event.planned;read['motion']['height']=555
    assert event.planned['motion']['height']==5.55 and event.planned['player'].y==176
    assert 'native'not in event.planned and 'health'not in event.planned
    with pytest.raises(FrozenInstanceError):event.action='down'


def test_time_reversal_invalid_key_and_unordered_ack_are_explicit_errors():
    actor,line=seed();key(line,'jump',1.2,'jump1')
    with pytest.raises(ValueError):key(line,'down',1.1,'air_down')
    with pytest.raises(ValueError):key(line,'down',1.3,'jump1')
    with pytest.raises(ValueError):line.before_observe(.99)
    with pytest.raises(ValueError):line.before_observe(1.)
    with pytest.raises(ValueError):line.project(.99)
    assert line.latest['time']==1. and actor.jump_count==0


def test_missing_or_predicted_body_cannot_confirm_new_contact():
    actor,line=seed(falling());result=observe_body(line,1.5,observed=False)
    assert result['jumps']==2 and result['motion']is not None
    real=observe_body(line,1.55,Box(172.,271.28,16.,37.44))
    assert real['jumps']==0 and real['rope_contact_observed']


def test_reset_drops_previous_episode_events_but_projection_pause_does_not():
    actor,line=seed();key(line,'jump',1.1,'jump1')
    assert line.project(1.3)['jumps']==1
    assert line.events and line.consumed==0
    line.reset()
    assert not line.events and line.latest is None
    with pytest.raises(RuntimeError):line.project(2.)


def test_observer_failure_is_explicit_until_episode_reset():
    actor,line=seed();key(line,'jump',1.1,'jump1')
    def broken(image,at):raise RuntimeError('synthetic observer failure')
    with pytest.raises(RuntimeError,match='synthetic'):line.observe(None,1.2,observer=broken)
    with pytest.raises(RuntimeError,match='Observation failed'):line.project(1.3)
    assert line.events and line.consumed==1
    line.reset();assert not line.failed


def test_cursor_has_no_detector_tracker_or_model_reference():
    actor,line=seed();cursor=ActionCursor.from_perception(actor)
    assert not any(key in vars(cursor)for key in ('detector','tracker','supports','model'))
    cursor.active_motion={'name':'jump1','started':1.}
    assert actor.active_motion is None


def test_missing_role_prefix_gets_replayed_context_without_replacing_real_pixels():
    from arena_obb_detector import missing_role_prediction
    actor,line=seed();key(line,'jump',1.1,'jump1');key(line,'down',1.2,'air_down')
    expected=line.project(1.23);old=actor.last_observation
    def observer(image,at):
        context,reason=line.missing_role_context()
        assert reason is None and context['motion']['name']=='air_down'
        assert context['time']==at and context['source_image_stamp']==1.
        assert context['player_predicted']and not context['rope_contact_observed']
        assert actor.last_observation is old
        player,cause=missing_role_prediction(context,at,at-1.)
        assert player==expected['player']and cause=='short_gap'
        return dict(context,player=player)
    # Use .21 so original missing-role .22 short-gap lease still applies.
    expected=line.project(1.21)
    observed=line.observe(None,1.21,observer=observer)
    assert observed['jumps']==1 and observed['player_predicted']


def test_missing_context_keeps_original_camera_plane_when_camera_is_moving():
    initial=standing();initial['camera_velocity_y']=40.
    actor,line=seed(initial);key(line,'jump',1.1,'jump1');line.before_observe(1.15)
    context,reason=line.missing_role_context()
    assert reason is None and context['camera_reference_y']==line.latest['camera_reference_y']
    # Forecast context does not replace real pixels or consume extra inputs.
    assert actor.last_observation is line.latest and line.latest['time']==1.
    assert line.consumed==1 and actor.active_motion['name']=='jump1'


def test_queued_event_sequence_is_readonly_to_callers():
    actor,line=seed();event=key(line,'jump',1.1,'jump1')
    assert line.events==(event,)
    with pytest.raises(AttributeError):line.events.append(event)


@pytest.mark.parametrize('camera_delta',[-12.,10.])
def test_missing_role_replay_adds_camera_translation_once(camera_delta):
    from arena_obb_detector import missing_role_prediction
    actor,line=seed();key(line,'jump',1.02,'jump1')
    expected=line.project(1.12)['player']
    def observer(image,at):
        context,reason=line.missing_role_context()
        assert reason is None and context['camera_reference_y']==260.
        predicted,_=missing_role_prediction(context,at,.12)
        shifted=Box(predicted.x,predicted.y+camera_delta,predicted.w,predicted.h)
        return dict(context,time=at,player=shifted,rope=260.+camera_delta,
                    camera_reference_y=260.+camera_delta,player_predicted=True)
    line.observe(None,1.12,observer=observer)
    actual=line.latest['player']
    assert actual.center[1]==pytest.approx(expected.center[1]+camera_delta)
    # The already measured image-plane shift must not be forecast a second time.
    projected=line.project(1.12)
    assert projected['player']==actual
    assert projected['jumps']==1 and not projected['rope_contact_observed']


def test_commit_action_queues_without_changing_actual_observed_phase():
    actor,line=seed();actor.input_timeline=line
    ack=SimpleNamespace(device_ready_ns=1_050_000_000)
    report=commit_action(actor,line.latest,'jump',ack,primitive='jump1',planned=line.latest)
    assert actor.active_motion is None and actor.jump_count==0
    assert report['committed_primitive']=='jump1'
    assert len(line.events)==1
    assert line.project(report['committed_time'])['jumps']==1


def test_missing_body_between_submission_and_consumption_keeps_key_without_inventing_player():
    actor,line=seed(falling())
    key(line,'jump',1.1,'air_up',line.latest)
    # The previous expected motion may outlive the detector's short gap lease.
    def missing(image,at):
        return dict(line.latest,time=at,player=None,phase='unknown',player_predicted=False,
                    rope_contact_observed=False,ground_contact_observed=False)
    line.observe(None,1.05,observer=missing)
    assert line.latest['player']is None and line.consumed==0
    future=line.project(1.12)
    assert future['player']is None and future['phase']=='unknown'
    assert future['replayed_event_ids']==[1]
    line.observe(None,1.12,observer=missing)
    assert line.consumed==1 and actor.active_motion['name']=='air_up'
    assert line.latest['player']is None
    assert not line.latest.get('rope_contact_observed')
