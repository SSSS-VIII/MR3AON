"""No native telemetry, repeat aliasing, premature loop wrap or duplicate keys."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_fixed_match as matching
from arena_fixed_match import Atlas,BoardTracker,landmark_shifts
from arena_fixed_match import static_box_anchor
from arena_fixed_policy import HybridAvoider,compile_program,compatible

ID=(5,42,1,50012)
KEY='L5-M42-S1-B50012'


def candidate(x, score=.95):
    return dict(row=dict(key=KEY),identity=ID,progress=x,std=.05,score=score)


class Bank:
    def __init__(self, *, loop=False,length=100):
        self.contexts={KEY:dict(key=KEY,length=length,loop=loop,blocks=[
            dict(index=0,start_x=0,finish_x=32),dict(index=1,start_x=32,finish_x=64)])}
        self.candidates=[]
    def match(self,*_):return deepcopy(self.candidates)


def observation(t,phase='rope_above'):
    return dict(time=t,phase=phase,jumps=0,player=object(),player_predicted=False,
                scene_motion_observed=True,scene_velocity_x=-395,scale_px=39.5,vx=0)


def test_same_looking_repetitions_without_progress_are_ambiguous():
    bank=Bank();bank.candidates=[candidate(10),candidate(42)]
    tracker=BoardTracker(bank)
    for t in (0,.05,.1):value=tracker.observe(None,observation(t))
    assert value['status']=='ambiguous' and not value['localized']


def test_photo_score_cannot_override_a_different_repetition_allowed_by_original_geometry():
    bank=Bank();tracker=BoardTracker(bank)
    bank.candidates=[dict(candidate(42,1),progress_source='static_foreground'),
        dict(candidate(10,.84),progress_source='original_static_layout',landmark_count=3)]
    for t in (0,.05,.1):value=tracker.observe(None,observation(t))
    assert value['status']=='ambiguous'and not value['localized']
    for t,x in ((.15,40),(.2,40.5),(.25,41)):
        bank.candidates=[candidate(x)];tracker.observe(None,observation(t))
    bank.candidates=[dict(candidate(42,1),progress_source='static_foreground'),
        dict(candidate(10,.84),progress_source='original_static_layout',landmark_count=3)]
    value=tracker.observe(None,observation(.3))
    assert value['localized']and value['progress_x']==42


def test_own_start_order_and_visual_motion_can_reject_a_different_repetition():
    bank=Bank();tracker=BoardTracker(bank);tracker.begin_episode(level=5,slot=1)
    bank.candidates=[candidate(42,1),candidate(10,.95)]
    for t in (0,.05,.1):value=tracker.observe(None,observation(t))
    assert value['localized']and value['progress_x']==10
    assert tracker.start_context is None


def test_short_occlusions_preserve_spatial_confirmation_without_merging_repetitions():
    bank=Bank();tracker=BoardTracker(bank)
    for t in (0,.05,.1,.15,.2):
        bank.candidates=[]if t in(.05,.15)else[candidate(10+10*t)]
        value=tracker.observe(None,observation(t))
        if t<.2:assert not value['localized']
    assert value['localized']and value['progress_x']==12
    other=BoardTracker(bank)
    for t,x in((0,10),(.1,42),(.2,11)):
        bank.candidates=[candidate(x)];value=other.observe(None,observation(t))
    assert not value['localized']


def test_temporally_tracked_entry_pair_still_requires_known_map_and_own_start():
    bank=Bank();bank.meta=dict(map_sequences=[dict(level=5,map=42,
        slots=[dict(slot=1,fixed=[50012],random=False)])])
    bank.candidates=[dict(candidate(10,.75),temporal_entry_pair=True)]
    tracker=BoardTracker(bank);tracker.begin_episode(level=5,slot=1)
    assert not tracker.observe(None,observation(0))['localized']
    other=BoardTracker(bank);other.begin_episode(level=5,slot=1)
    for _ in range(3):other.sequence.background({(5,42):1.})
    assert other.observe(None,observation(0))['localized']
    no_start=BoardTracker(bank)
    for _ in range(3):no_start.sequence.background({(5,42):1.})
    assert not no_start.observe(None,observation(0))['localized']


def test_own_start_context_cannot_create_a_location_from_background_or_ignore_missing_motion():
    bank=Bank();tracker=BoardTracker(bank);tracker.begin_episode(level=5,slot=1)
    bank.candidates=[dict(candidate(0),progress=None)]
    for t in (0,.05,.1):value=tracker.observe(None,observation(t))
    assert not value['localized']and tracker.last is None
    tracker.observe(None,dict(observation(1.1),scene_motion_observed=False))
    assert tracker.start_context['high']>40
    tracker.observe(None,observation(9))
    assert tracker.start_context is None


def test_forward_prior_rejects_an_earlier_identical_pattern_and_tracks_block_instance():
    bank=Bank();tracker=BoardTracker(bank)
    for t,x in ((0,40),(.05,40.5),(.1,41)):
        bank.candidates=[candidate(x)];tracker.observe(None,observation(t))
    bank.candidates=[candidate(10,1),candidate(42,.92)]
    value=tracker.observe(None,observation(.15))
    assert value['progress_x']==42 and value['block_instance']==1
    bank.candidates=[candidate(41.95)]
    assert tracker.observe(None,observation(.2))['progress_x']==42


def test_loop_cannot_reset_before_visual_odometry_reaches_its_end():
    bank=Bank(loop=True,length=64);tracker=BoardTracker(bank)
    for t,x in ((0,62.8),(.05,63.3),(.1,63.8)):
        bank.candidates=[candidate(x)];tracker.observe(None,observation(t))
    visit=tracker.visit
    bank.candidates=[candidate(.3)]
    value=tracker.observe(None,observation(.15))
    assert value['loop_cycle']==1 and value['visit']==visit+1
    assert abs(value['absolute_progress']-64.3)<1e-6
    bank2=Bank(loop=True,length=64);other=BoardTracker(bank2)
    for t in (0,.05,.1):
        bank2.candidates=[candidate(40)];other.observe(None,observation(t))
    bank2.candidates=[candidate(.3)]
    assert other.observe(None,observation(.15))['progress_x']>40
    assert other.cycle==0


def test_short_visual_occlusion_keeps_measured_progress_then_expires_with_uncertainty():
    bank=Bank();tracker=BoardTracker(bank)
    for t,x in ((0,20),(.05,20.5),(.1,21)):
        bank.candidates=[candidate(x)];tracker.observe(None,observation(t))
    bank.candidates=[]
    assert tracker.observe(None,observation(.15))['progress_x']==21.5
    value=None
    for tick in range(4,35):
        value=tracker.observe(None,dict(observation(tick*.05),scene_motion_observed=False))
    assert not value['localized']


def test_an_already_identified_board_can_localize_a_brief_distinctive_pattern():
    bank=Bank();tracker=BoardTracker(bank)
    for t in (0,.05,.1):
        bank.candidates=[dict(candidate(0),progress=None)]
        tracker.observe(None,observation(t))
    assert tracker.state['status']=='tentative'and tracker.state['identity']is None
    bank.candidates=[];tracker.observe(None,observation(.15))
    bank.candidates=[candidate(47.8)]
    assert tracker.observe(None,observation(.2))['localized']


def test_static_foreground_translation_retains_repeated_hypotheses():
    a=np.array([[1,-80,100],[1,0,110],[1,80,120]],np.float32)
    b=a.copy();b[:,1]-=20
    result=landmark_shifts(dict(landmarks=a,landmark_count=3),dict(landmarks=b,landmark_count=3))
    assert any(abs(r['dx']+20)<.1 and r['count']==3 for r in result)


def test_an_extra_dynamic_hazard_does_not_erase_aligned_static_geometry(tmp_path,monkeypatch):
    import json
    context=dict(key=KEY,level=5,map=42,slot=1,stage=50012,length=64,fixed=False)
    (tmp_path/'index.json').write_text(json.dumps(dict(schema=1,mode=6,contexts=[context],
        references=[dict(context,local_x=10)])))
    ref=dict(coarse=np.ones(64,np.float32),points=np.zeros((128,2),np.float32),
        descriptors=np.zeros((128,32),np.uint8),count=22,semantic=np.zeros(32,np.float32),
        landmarks=np.zeros((48,3),np.float32),landmark_count=3)
    ref['landmarks'][:3]=[[3,-40,260],[3,40,260],[3,120,260]]
    np.savez_compressed(tmp_path/'features.npz',**{k:np.asarray([v])for k,v in ref.items()})
    query=deepcopy(ref);query['landmarks'][:3,1]-=20;query['semantic'][5*4]=1
    monkeypatch.setattr(matching,'features',lambda *_:query)
    monkeypatch.setattr(matching,'register',lambda *_:dict(inliers=22,ratio=1.,residual=0.,dx=0.,dy=0.))
    bank=Atlas(tmp_path)
    assert any(c['progress_source']=='static_foreground'and c['score']>=.42 for c in bank.match(None,{}))
    query['landmark_count']=0
    assert bank.match(None,{})==[]


class Reactive:
    def __init__(self):self.last_action=0;self.calls=0
    def choose(self,obs):self.calls+=1;return 'jump','reactive'
    def uses_search(self,obs):return True


def controller():
    program=dict(entry_x=0,end_x=32,poses=[dict(x=0,phase='rope_above',jumps=0),
        dict(x=10,phase='rope_above',jumps=0),dict(x=10.2,phase='flip_down',jumps=0),
        dict(x=14,phase='rope_below',jumps=0)],events=[dict(index=0,x=10,action='down',
        primitive='rope_down',before='rope_above',before_jumps=0)])
    reactive=Reactive();policy=HybridAvoider(reactive,Bank(),{KEY:program})
    policy.tracker=SimpleNamespace(projected=lambda obs:dict(key=KEY,visit=1,localized=True,
        progress_x=obs['test_progress'],progress_std=.1,status='locked'))
    return policy,reactive


def test_future_position_uses_pre_input_pose_and_cursor_advances_only_on_ack():
    policy,reactive=controller();obs=dict(observation(1),test_progress=10.3)
    assert policy.choose(obs)[0]=='down'
    assert policy.choose(obs)[0]=='down'  # No acknowledgement yet.
    policy.on_commit('down',1.02)
    later=dict(observation(1.1,phase='flip_down'),test_progress=11)
    assert policy.choose(later)[0]is None
    assert reactive.calls==0


def test_resting_pose_after_a_missed_input_cannot_skip_to_a_later_operation():
    policy,reactive=controller()
    program=policy.programs[KEY]
    program['events'].append(dict(index=1,x=22,action='jump',primitive='jump1',before='rope_above'))
    program['poses'].append(dict(x=20,phase='rope_above',jumps=0))
    # An early visual lock creates cursor 0, but no key was acknowledged.
    assert policy.choose(dict(observation(1),test_progress=8))[0]is None
    assert policy.cursor==0
    assert policy.choose(dict(observation(1.5),test_progress=22))==('jump','reactive')
    assert policy.cursor==0 and policy.decision['reason']=='missed_fixed_input_window'
    policy.on_commit('jump',1.51)
    assert policy.cursor==0
    assert policy.choose(dict(observation(1.6),test_progress=10))==('jump','reactive')
    assert policy.decision['reason']=='fixed_sequence_aborted'


def test_initial_takeover_cannot_start_at_a_later_operation_in_a_repetition():
    policy,_=controller()
    policy.programs[KEY]['events'].append(dict(index=1,x=22,action='jump',primitive='jump1',before='rope_above'))
    policy.programs[KEY]['poses'].append(dict(x=20,phase='rope_above',jumps=0))
    assert policy.choose(dict(observation(1),test_progress=22))==('jump','reactive')
    assert policy.cursor==0 and policy.proposed_event is None


def test_action_sequence_restricts_repeat_registration_without_manufacturing_a_place():
    bank=Bank();tracker=BoardTracker(bank)
    for t,x in ((0,8),(.05,8.5),(.1,9)):
        bank.candidates=[candidate(x)];tracker.observe(None,observation(t))
    tracker.action_window=dict(key=KEY,visit=tracker.visit,low=8,high=10.65,event=0)
    # Absolute odometry is deliberately uncertain. A far repetition cannot
    # replace the expected next input even when it has the stronger image.
    tracker.last['std']=2
    bank.candidates=[candidate(42,1),candidate(10,.94)]
    value=tracker.observe(None,observation(.15))
    assert value['localized']and value['progress_x']==10
    bank.candidates=[candidate(42,1)]
    tracker.last['std']=2
    value=tracker.observe(None,observation(.2))
    assert not value['localized']
    assert not tracker.projected(observation(.21))['localized']


def test_policy_supplies_only_the_next_unacknowledged_operation_window():
    policy,_=controller()
    policy.tracker.observe=lambda *_:policy.tracker.action_window
    policy.visit=(KEY,1);policy.cursor=0
    value=policy.observe(None,observation(1))
    assert value['event']==0 and value['high']==10.65
    assert value['low']==-.2
    policy.proposed_event=policy.programs[KEY]['events'][0];policy.on_commit('down',1)
    assert policy.observe(None,observation(1.1))is None


def test_first_operation_can_use_a_trap_and_rope_joint_but_not_a_later_identical_pair(tmp_path,monkeypatch):
    import json
    context=dict(key=KEY,level=5,map=42,slot=1,stage=50012,length=100,fixed=True,
        anchors=[[2,32],[2,64]],support_anchors=[[4,24],[4,56]])
    (tmp_path/'index.json').write_text(json.dumps(dict(schema=1,mode=6,contexts=[context],
        references=[dict(context,local_x=20)])))
    value=dict(coarse=np.ones(64,np.float32),points=np.zeros((128,2),np.float32),
        descriptors=np.zeros((128,32),np.uint8),count=8,semantic=np.zeros(32,np.float32),
        landmarks=np.zeros((48,3),np.float32),landmark_count=0)
    np.savez_compressed(tmp_path/'features.npz',**{k:np.asarray([v])for k,v in value.items()})
    query=deepcopy(value);query['landmark_count']=2
    query['landmarks'][:2]=[[2,12*39.5,100],[4,4*39.5,150]]
    monkeypatch.setattr(matching,'features',lambda *_:query)
    monkeypatch.setattr(matching,'register',lambda *_:dict(inliers=22,ratio=1.,residual=0.,dx=0.,dy=0.))
    bank=Atlas(tmp_path);bank.entry_windows={KEY:dict(low=0,high=30)}
    positions=[c['progress']for c in bank.match(None,{})if c['progress']is not None]
    assert positions and all(abs(x-20)<.01 for x in positions)
    query['landmark_count']=1  # The joint leaves view after the initial pair.
    assert not any(c['progress']is not None for c in bank.match(None,{}))
    prior=dict(identity=ID,progress=20,std=.3,length=100,tentative=True)
    continued=[c for c in bank.match(None,{},prior)if c['progress']is not None]
    assert continued and all(abs(c['progress']-20)<.01 for c in continued)
    bank.entry_windows={}
    assert not any(c['progress']is not None for c in bank.match(None,{}))


def test_missing_visual_lock_and_wrong_jump_count_use_the_existing_reactive_policy():
    policy,reactive=controller();obs=dict(observation(1),test_progress=8,player_predicted=True)
    assert policy.choose(obs)==('jump','reactive')
    program=policy.programs[KEY];program['poses']=[dict(x=0,phase='air',jumps=1)]
    obs=dict(observation(1,'air_falling2'),test_progress=8,jumps=2)
    assert policy.choose(obs)==('jump','reactive')
    assert reactive.calls==2


def test_live_native_ids_in_an_observation_cannot_override_visual_identity():
    policy,_=controller()
    obs=dict(observation(1),test_progress=10,stageID=999,map=1,health=1,native_x=1e8)
    assert policy.choose(obs)[0]=='down'
    assert policy.decision['board']['key']==KEY


def test_original_first_jump_and_fall_keep_one_consumed_jump_until_rope_contact():
    def state(x,physics):return dict(health=5000,position=dict(x=x,y=.75),physics=physics)
    steps=[]
    sequence=[('runOnLine: 1','jump','jump: 14'),('jump: 14','none','fall: 15'),
              ('fall: 15','jump','jump2: 16'),('jump2: 16','none','fall: 15'),
              ('runOnLine: 1','jump','jump: 14')]
    for i,(before,action,after)in enumerate(sequence):
        steps.append(dict(before=state(i,before),after=state(i+.5,after),action=action,relative_tick=i*3))
    route=dict(complete=True,uses_restart_replay=False,start=dict(health=5000,board=dict(stage_start=0)),
               steps=steps,end=dict(state=state(5,'jump: 14')))
    program=compile_program(route,KEY)
    assert [p['jumps']for p in program['poses']]==[0,1,1,2,0]
    assert [e['before_jumps']for e in program['events']]==[0,1,0]
    assert program['events'][1]['primitive']=='jump2'


def test_visual_jump_phases_match_native_air_without_reactive_down_interruptions():
    for name,jumps in [('jump1_rising',1),('jump1_falling',1),('jump2_rising',2),('jump2_falling',2),('air_falling',0)]:
        assert compatible('air',dict(phase=name,jumps=jumps),jumps)
        assert not compatible('air',dict(phase=name,jumps=jumps),jumps+1)
    policy,reactive=controller()
    policy.programs[KEY]['poses']=[dict(x=0,phase='air',jumps=1)]
    policy.programs[KEY]['events']=[]
    assert policy.choose(dict(observation(1,'jump1_falling'),test_progress=8,jumps=1))==(None,'fixed_route_wait')
    assert reactive.calls==0


def test_short_action_combination_uses_its_ack_clock_without_waiting_for_a_late_position():
    policy,_=controller()
    policy.tracker.last_velocity=18.5
    first=dict(index=0,x=10,action='jump',primitive='rope_up',before='rope_below',
               before_jumps=0,relative_tick=50)
    second=dict(index=1,x=11.85,action='down',primitive='air_down',before='flip_up',
                before_jumps=0,relative_tick=55)
    policy.programs[KEY]['events']=[first,second]
    policy.visit=(KEY,1);policy.cursor=0;policy.proposed_event=first
    policy.on_commit('jump',1.)
    obs=dict(observation(1.09,'flip_up'),test_progress=11.2,decision_interval_seconds=.04)
    assert policy.choose(obs)==(None,'fixed_route_short_combo_wait')
    obs['test_progress']=11.6
    assert policy.choose(obs)==('down','fixed_route_air_down')
    policy.on_commit('down',1.1)
    assert policy.cursor==2


def test_vertical_pose_cannot_fire_down_before_the_recorded_spatial_boundary():
    from arena_vision import Box
    policy,_=controller()
    policy.tracker.last_velocity=18.5
    event=dict(index=1,x=11.85,action='down',before='flip_up',before_rope_height=-.2)
    obs=dict(observation(1,'flip_up'),decision_interval_seconds=.04,
             player=Box(170,245,16,30),rope=260,scale_px=40)
    assert not policy.input_due(event,obs,10.5)
    assert not policy.input_due(event,obs,11.4)
    assert policy.input_due(event,obs,11.5)


def test_second_jump_keeps_its_recorded_frame_gap_after_the_own_first_jump():
    policy,_=controller();policy.visit=(KEY,1)
    policy.last_fixed_commit=dict(visit=policy.visit,time=1.,event=dict(index=0,relative_tick=100))
    second=dict(index=1,x=20,relative_tick=128,before='air')
    assert not policy.input_due(second,dict(observation(1.3),decision_interval_seconds=.04),20)
    assert policy.input_due(second,dict(observation(1.55),decision_interval_seconds=.04),20)


def test_generic_boxes_require_measured_static_horizontal_motion_to_anchor_live_progress():
    from arena_vision import Box,Detection
    detection=Detection(Box(300,150,10,80),'trap',.9,collider_shape='BoxCollider')
    track=SimpleNamespace(kind='trap',collider_shape='BoxCollider',observations=4,
        seen=1,box=detection.box,vx=-740)
    obs=dict(time=1,scene_velocity_x=-741,scene_motion_observed=True,tracks=[track])
    assert static_box_anchor(detection,obs)
    track.vx=-1000
    assert not static_box_anchor(detection,obs)
    track.vx=-740;track.observations=1
    assert not static_box_anchor(detection,obs)
    assert not static_box_anchor(detection,dict(obs,scene_motion_observed=False))


def test_adjacent_rope_segments_supply_one_shared_joint_but_keep_distinct_endpoints():
    from arena_vision import Box
    supports=[dict(kind='rope',confidence=.9,a=(0,250),b=(400,250),left_clipped=True),
        dict(kind='rope',confidence=.9,a=(410,252),b=(640,250),right_clipped=True),
        dict(kind='rope',confidence=.9,a=(420,250),b=(640,250),right_clipped=True)]
    q=matching.features(np.zeros((360,640,3),np.uint8),dict(player=Box(170,210,16,36),visible_supports=supports))
    points=q['landmarks'][:q['landmark_count']]
    assert len(points)==2 and all(points[:,0]==4)
    assert abs(points[1,1]-points[0,1]-20)<.01


def test_offline_generic_box_reference_needs_a_declared_static_x_correspondence():
    from arena_vision import Box,Detection
    detection=Detection(Box(300,150,10,80),'trap',.9,collider_shape='BoxCollider')
    assert static_box_anchor(detection,dict(reference_static_box_x=[307]))
    assert not static_box_anchor(detection,dict(reference_static_box_x=[325]))
    assert not static_box_anchor(detection,{})


def test_runtime_rejects_a_bank_compiled_with_different_anchor_semantics(tmp_path,monkeypatch):
    import json
    import arena_fixed_policy as policy_module
    atlas=tmp_path/'atlas';atlas.mkdir()
    (atlas/'index.json').write_text('{}');(atlas/'features.npz').write_bytes(b'features')
    programs=tmp_path/'programs.json';programs.write_text(json.dumps(dict(schema=1,programs={})))
    config=tmp_path/'config.json';config.write_text(json.dumps(dict(schema=1,atlas=str(atlas),programs=str(programs))))
    bank=SimpleNamespace(folder=atlas,meta=dict(detector_sha256='detector',feature_sha256='old'),contexts={})
    monkeypatch.setattr(policy_module,'Atlas',lambda _:bank)
    reactive=Reactive()
    assert policy_module.load(reactive,config,detector_sha256='detector')is reactive
    bank.meta['feature_sha256']=matching.feature_signature()
    assert isinstance(policy_module.load(reactive,config,detector_sha256='detector'),HybridAvoider)


def test_reference_box_features_and_cache_follow_the_offline_static_layout(tmp_path):
    import cv2
    from arena_vision import Box,Detection
    from arena_fixed_build import build
    image=tmp_path/'native.png'
    gray=np.random.default_rng(4).integers(0,256,(360,640),dtype=np.uint8)
    cv2.imwrite(str(image),np.repeat(gray[:,:,None],3,axis=2))
    calls=[]
    class Detector:
        def detect(self,pixels):
            calls.append(1)
            return Box(172,210,16,40),[Detection(Box(300,150,10,80),'trap',.95,collider_shape='BoxCollider')],[]
    sample=dict(key=KEY,level=5,map=42,slot=1,stage=50012,loop=False,fixed=True,
        classification={},length=64,blocks=[],local_x=20,image=str(image),episode='native-reference',
        anchors=[[2,20+(305-(180-.052*39.5))/39.5]])
    build([sample],tmp_path/'first',Detector(),cache=tmp_path/'cache')
    with np.load(tmp_path/'first/features.npz')as data:
        assert data['landmark_count'][0]==1 and data['landmarks'][0,0,0]==2
    changed=dict(sample,anchors=[[2,40]])
    build([changed],tmp_path/'second',Detector(),cache=tmp_path/'cache')
    with np.load(tmp_path/'second/features.npz')as data:assert data['landmark_count'][0]==0
    assert len(calls)==2


def test_visual_pose_bridge_uses_existing_flip_risk_and_does_not_consume_tape_events():
    policy,reactive=controller()
    policy.tracker.last_velocity=18.5
    reactive._risk=lambda *_:(0,10,{})
    obs=dict(observation(1,'rope_below'),test_progress=2,rope=260)
    action,reason=policy.choose(obs)
    assert (action,reason)==('jump','fixed_entry_sync_rope_up')
    assert policy.proposed_primitive=='rope_up'and policy.proposed_event is None
    policy.on_commit(action,1.02)
    assert policy.cursor is None and policy.decision['mode']=='synchronizing'
    reactive._risk=lambda *_:(100,.2,{1:object()})
    assert policy.choose(obs)==('jump','reactive')
    reactive._risk=lambda *_:(0,10,{})
    assert policy.choose(dict(obs,test_progress=8))==('jump','reactive')
    assert policy.choose(dict(obs,player_predicted=True))==('jump','reactive')


def test_brief_place_loss_after_a_confirmed_jump_does_not_insert_reactive_down():
    policy,reactive=controller()
    first=dict(index=0,x=3,action='jump',primitive='jump1',before='rope_above',relative_tick=0)
    second=dict(index=1,x=14,action='jump',primitive='jump2',before='air',before_jumps=1,relative_tick=30)
    policy.programs[KEY]['events']=[first,second]
    policy.visit=(KEY,1);policy.cursor=0;policy.proposed_event=first
    policy.on_commit('jump',1)
    policy.tracker.projected=lambda obs:dict(key=KEY,visit=1,localized=False,status='identified')
    reactive._risk=lambda *_:(200,.4,{})
    obs=dict(observation(1.2,'jump1_rising'),jumps=1)
    assert policy.choose(obs)==(None,'fixed_route_relocalize_wait')
    assert policy.cursor==1 and reactive.calls==0
    reactive._risk=lambda *_:(200,.1,{})
    assert policy.choose(obs)==('jump','reactive')
    reactive._risk=lambda *_:(0,10,{})
    assert policy.choose(dict(obs,time=1.55))==('jump','reactive')
    assert policy.choose(dict(obs,time=2))==('jump','reactive')


def test_short_own_input_pair_needs_recent_ack_current_pose_and_bounded_position():
    policy,reactive=controller()
    first=dict(index=0,x=10,action='jump',primitive='rope_up',before='rope_below',relative_tick=0)
    second=dict(index=1,x=11.85,action='down',primitive='air_down',before='flip_up',relative_tick=5)
    policy.programs[KEY]['events']=[first,second]
    policy.visit=(KEY,1);policy.cursor=0;policy.proposed_event=first;policy.on_commit('jump',1)
    policy.tracker.last_velocity=18.5
    policy.tracker.projected=lambda obs:dict(key=KEY,visit=1,localized=False,status='identified',
        progress_x=11.8,progress_std=obs.get('test_std',.65))
    obs=dict(observation(1.1,'flip_up'),decision_interval_seconds=.04)
    assert policy.choose(obs)==('down','fixed_route_air_down')
    assert policy.cursor==1
    policy.on_commit('down',1.11)
    assert policy.cursor==2
    policy.cursor=1;policy.last_fixed_commit=dict(event=first,time=1,visit=(KEY,1))
    assert policy.choose(dict(obs,test_std=1.5))==('jump','reactive')
    assert policy.choose(dict(obs,time=1.3))==('jump','reactive')
    assert policy.choose(dict(obs,phase='rope_below'))==('jump','reactive')


def test_short_action_clock_cannot_fire_an_early_key_in_another_visit():
    policy,_=controller()
    event=dict(index=1,x=11.85,relative_tick=55,before='flip_up')
    policy.visit=(KEY,2)
    policy.last_fixed_commit=dict(visit=(KEY,1),time=1.,event=dict(index=0,relative_tick=50))
    assert not policy.input_due(event,dict(observation(1.2),decision_interval_seconds=.04),11.2)


def test_original_static_layout_localizes_a_pattern_without_a_nearby_reference_photo(tmp_path,monkeypatch):
    import json
    anchors=[(1,40),(1,44.7),(1,49.1),(1,55.3),(1,61.8)]
    context=dict(key=KEY,level=5,map=42,slot=1,stage=50012,length=212,fixed=True,anchors=anchors)
    # The only photograph is the empty beginning; geometry is the recovered
    # whole-board declaration, not another saved image of this pose.
    (tmp_path/'index.json').write_text(json.dumps(dict(schema=1,mode=6,
        contexts=[context],references=[dict(context,local_x=8)])))
    value=dict(coarse=np.ones(64,np.float32),points=np.zeros((128,2),np.float32),
        descriptors=np.zeros((128,32),np.uint8),count=8,semantic=np.zeros(32,np.float32),
        landmarks=np.zeros((48,3),np.float32),landmark_count=0)
    np.savez_compressed(tmp_path/'features.npz',**{k:np.asarray([v])for k,v in value.items()})
    query=deepcopy(value);query['landmark_count']=len(anchors)
    query['landmarks'][:len(anchors)]=[[kind,(x-50)*39.5,100]for kind,x in anchors]
    monkeypatch.setattr(matching,'features',lambda *_:query)
    monkeypatch.setattr(matching,'register',lambda *_:dict(inliers=22,ratio=1.,residual=0.,dx=0.,dy=0.))
    bank=Atlas(tmp_path)
    found=bank.match(None,{})
    assert any(c['progress_source']=='original_static_layout'and abs(c['progress']-50)<.01 for c in found)
    assert all(c['progress']is None for c in found if c['progress_source']!='original_static_layout')
    query['landmarks'][:len(anchors),0]=3  # Platforms cannot impersonate these enemy anchors.
    assert not any(c['progress_source']=='original_static_layout'for c in bank.match(None,{}))


def test_visual_next_board_keeps_odometry_instead_of_resetting_to_an_unknown_origin():
    bank=Bank(length=64);bank.contexts[KEY]['fixed']=True
    next_key='L5-M42-S2-B50022';next_identity=(5,42,2,50022)
    bank.contexts[next_key]=dict(key=next_key,length=278,fixed=True,blocks=[])
    tracker=BoardTracker(bank)
    for t,x in ((0,62.8),(.05,63.3),(.1,63.8)):
        bank.candidates=[candidate(x)];tracker.observe(None,observation(t))
    visit=tracker.visit
    bank.candidates=[dict(row=dict(key=next_key),identity=next_identity,progress=None,std=.1,score=.95)]
    for t in (.15,.2,.25):
        value=tracker.observe(None,dict(observation(t),detections=[object()]))
    assert value['key']==next_key and value['visit']==visit+1
    assert abs(value['progress_x']-1.3)<1e-6
    assert value['localized']


def test_stale_absolute_position_cannot_seed_a_periodic_single_anchor():
    bank=Bank();tracker=BoardTracker(bank)
    for t,x in ((0,20),(.05,20.5),(.1,21)):
        bank.candidates=[candidate(x)];tracker.observe(None,observation(t))
    assert tracker.recognition_prior(.15)is not None
    stale=tracker.recognition_prior(2)
    assert stale['identity']==ID and stale['progress']is None
    assert not stale['near_exit']
    assert tracker.recognition_prior(10)is None


def test_loss_of_precise_progress_preserves_verified_board_order_without_periodic_position():
    bank=Bank(length=64);tracker=BoardTracker(bank)
    for t,x in ((0,60),(.05,60.5),(.1,61)):
        bank.candidates=[candidate(x)];tracker.observe(None,observation(t))
    tracker.last['std']=2
    used=[]
    def match(image,obs,prior):used.append(prior);return []
    bank.match=match
    assert not tracker.observe(None,observation(.15))['localized']
    assert used[-1]['identity']==ID and used[-1]['near_exit']
    assert used[-1]['progress']is None


def test_uncertain_next_board_carry_cannot_control_until_new_spatial_registration():
    bank=Bank(length=64);bank.contexts[KEY]['fixed']=True
    next_key='L5-M42-S2-B50022';next_id=(5,42,2,50022)
    bank.contexts[next_key]=dict(key=next_key,length=100,loop=False,blocks=[])
    tracker=BoardTracker(bank)
    for t,x in ((0,63),(.05,63.5),(.1,64)):
        bank.candidates=[candidate(x)];tracker.observe(None,observation(t))
    tracker.last['std']=.65
    bank.candidates=[dict(row=dict(key=next_key),identity=next_id,progress=None,std=float('inf'),score=.95)]
    for t in (.15,.2,.25):value=tracker.observe(None,dict(observation(t),detections=[object()]))
    assert value['key']==next_key and not value['localized']
    assert tracker.last['identity']==next_id and tracker.last['std']>.5
    bank.candidates=[dict(row=dict(key=next_key),identity=next_id,progress=2,std=.1,score=.95)]
    value=tracker.observe(None,observation(.3))
    assert value['localized']and value['progress_x']==2
