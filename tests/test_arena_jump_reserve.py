"""Recover renewable rope actions only through collision-safe native paths."""
from pathlib import Path
import sys
import pytest

pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Track
from arena_mpc import MpcAvoider,start_action,advance


def exhausted():
    return dict(time=1.,player=Box(172,70,16,37),phase='jump2_falling',
                jumps=2,motion=None,rope=260.,terrain=None,scale_px=40.,
                vy=60.,stand_w=14.4,stand_h=37.44,tracks=[])


def test_clear_airborne_runner_recovers_to_upper_rope_then_can_jump_again():
    state=exhausted();planner=MpcAvoider()
    assert planner.choose(state)==('down','mpc_air_down')
    rolling=advance(start_action(state,'air_down'),.12)
    assert rolling['jumps']==2
    assert planner.choose(rolling)==('jump','mpc_air_up')
    landed=advance(start_action(rolling,'air_up'),.2)
    assert landed['phase']=='rope_above'and landed['jumps']==0
    assert 'jump1'in planner._options(landed,landed['time'])
    assert not landed.get('ground_contact_observed',False)


def test_recovery_preference_does_not_descend_through_a_visible_hazard():
    state=exhausted()
    state['tracks']=[Track(1,Box(165,150,30,16),'trap',.99,1.,
                          observations=6,collider_shape='BoxCollider')]
    assert MpcAvoider().choose(state)==(None,'mpc_wait')


def test_prediction_does_not_schedule_inputs_faster_than_execution_allows():
    planner=MpcAvoider();state=start_action(exhausted(),'air_down')
    assert planner._options(advance(state,.08),1.08)==[None]
    assert 'air_up'in planner._options(advance(state,.12),1.12)


def test_safe_standing_runner_does_not_jump_to_collect_a_recovery_bonus():
    state=dict(exhausted(),player=Box(172,211.28,14.4,37.44),
               phase='rope_above',jumps=0,vy=0.)
    assert MpcAvoider().choose(state)[0]is None
