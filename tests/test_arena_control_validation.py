"""Ground down must still have a finite landing target when submitted."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from arena_vision import Box
from arena_input_timeline import advance,thaw_pixels
from arena_support import describe_terrain
from arena_control_validation import (FRAME,ground_down_commit_check,
                                      needs_ground_down_check,validate_ground_down)
from arena_action_timing import selected_primitive
from arena_policy import Avoider


def roomy():
    floor=dict(id=1,kind='platform',a=(0.,260.),b=(640.,260.),vx=-200.,vy=0.,confidence=.95)
    return dict(time=1.,player=Box(172,111.28,16,37.44),phase='jump2_falling',jumps=2,motion=None,
                terrain=describe_terrain([floor],floor,180),rope=None,scale_px=40.,vy=150.,vx=0.,
                stand_w=16.,stand_h=37.44,tracks=[])


def expired():
    data=json.loads((Path(__file__).parent/'fixtures/arena-ground-down-expired-ack.json').read_text())
    return thaw_pixels(json.dumps(data['planned'])),thaw_pixels(json.dumps(data['receipt']))


def test_actual_expired_down_is_canceled_without_a_false_input_cooldown():
    planned,current=expired();original=deepcopy(current);policy=SimpleNamespace(last_action=current['time']+.1)
    action,result=validate_ground_down(policy,'down','air_down',planned,
        lambda at:advance(current,at,forecast_contact=False),current['time']+.000001,123.)
    assert action is None and not result['allowed']and policy.last_action==123.
    assert result['reason']=='ground_down_target_unavailable'
    assert len(result['samples'])==3
    assert current==original


def test_roomy_visible_floor_remains_eligible_and_keeps_the_chooser_clock():
    state=roomy();policy=SimpleNamespace(last_action=1.02)
    action,result=validate_ground_down(policy,'down','air_down',state,
        lambda at:advance(state,at,forecast_contact=False),1.,.5)
    assert action=='down'and result['allowed']and policy.last_action==1.02
    assert [r['delay']for r in result['samples']]==[0.,FRAME,2*FRAME]
    assert {r['surface_id']for r in result['samples']}=={1}


def test_switching_between_landing_hypotheses_does_not_certify_one_target():
    def project(at):
        state=roomy()
        if at>1.+FRAME:
            state['terrain']['selected_id']=2
            state['terrain']['segments'][0]['id']=2
        return state
    result=ground_down_commit_check(project,1.)
    assert not result['allowed']and result['reason']=='ground_down_target_changes'


def test_missing_replay_context_cannot_submit_a_ground_down():
    state=roomy();policy=SimpleNamespace(last_action=2.)
    action,result=validate_ground_down(policy,'down','air_down',state,None,1.,.5)
    assert action is None and result['reason']=='no_own_input_timeline'and policy.last_action==.5


def test_ordinary_jump_slide_and_rope_down_do_not_enter_the_ground_check():
    state=roomy();policy=SimpleNamespace(last_action=2.)
    def forbidden(at):raise AssertionError('Unrelated input was projected')
    for action,primitive in [('jump','jump2'),('slide','slide'),('down','rope_down')]:
        value,check=validate_ground_down(policy,action,primitive,state,forbidden,1.,.5)
        assert value==action and check is None
    assert not needs_ground_down_check('down','air_down',dict(state,rope=260.))
    assert policy.last_action==2.
    assert Avoider.revalidate_ground_down is False


def test_reactive_and_mpc_air_down_keep_the_same_explicit_input_metadata():
    assert selected_primitive('down','air_down:34')=='air_down'
    assert selected_primitive('down','mpc_air_down')=='air_down'
    assert selected_primitive('jump','air_down:34')is None
    assert selected_primitive('down','flip:34')is None
