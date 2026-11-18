"""No native telemetry, repeat aliasing, premature loop wrap or duplicate keys."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_fixed_match as matching
from arena_fixed_match import Atlas,BoardTracker,landmark_shifts
from arena_fixed_policy import HybridAvoider

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


def test_short_action_combination_uses_its_ack_clock_without_waiting_for_a_late_position():
    policy,_=controller()
    first=dict(index=0,x=10,action='jump',primitive='rope_up',before='rope_below',
               before_jumps=0,relative_tick=50)
    second=dict(index=1,x=11.85,action='down',primitive='air_down',before='flip_up',
                before_jumps=0,relative_tick=55)
    policy.programs[KEY]['events']=[first,second]
    policy.visit=(KEY,1);policy.cursor=0;policy.proposed_event=first
    policy.on_commit('jump',1.)
    obs=dict(observation(1.09,'flip_up'),test_progress=11.2,decision_interval_seconds=.04)
    assert policy.choose(obs)==('down','fixed_route_air_down')
    policy.on_commit('down',1.1)
    assert policy.cursor==2


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
    assert tracker.recognition_prior(2)is None
