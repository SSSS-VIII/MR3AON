"""A known safe floor can restore spent jumps before the next hazard arrives."""
from pathlib import Path
import sys,json
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_mpc import MpcAvoider,start_action,advance
from arena_vision import Box,can_air_down
from arena_support import describe_terrain


class GroundReserve(MpcAvoider):
    ground_reserve_recovery=True


def observation():
    obs=json.loads((Path(__file__).parent/'fixtures/arena-ground-reserve.json').read_text())['observation']
    obs['player']=Box(**obs['player'])
    return obs


def test_clear_airborne_interval_can_restore_jumps_on_a_visible_floor():
    obs=observation();planner=GroundReserve()
    assert can_air_down(obs)
    assert not MpcAvoider().recovery_needed(obs)
    assert MpcAvoider().choose(obs)==(None,'clear')
    assert planner.recovery_needed(obs)and planner.uses_search(obs)
    assert planner.choose(obs)==('down','mpc_air_down')
    landed=advance(start_action(obs,'air_down'),.5)
    assert landed['phase']=='ground'and landed['jumps']==0
    assert obs['jumps']==2 and obs['phase']=='jump2_falling'
    assert planner.reserve_cost(landed)==0


def test_unknown_floor_or_gap_is_not_a_recovery_destination():
    obs=observation();planner=GroundReserve()
    assert not planner.recovery_needed(dict(obs,terrain=None))
    assert not planner.recovery_needed(dict(obs,terrain=dict(obs['terrain'],source='unknown')))
    floor=dict(id=1,kind='platform',a=(0.,260.),b=(100.,260.),vx=-760.,vy=0.,right_clipped=False)
    obs['terrain']=describe_terrain([floor],floor,180.)
    assert not can_air_down(obs)and not planner.recovery_needed(obs)
    assert not planner.recovery_needed(dict(observation(),player=None))


def test_grounded_state_and_original_input_cooldown_remain_constraints():
    obs=observation();planner=GroundReserve()
    assert not planner.recovery_needed(dict(obs,phase='ground',jumps=0))
    planner.last_action=obs['time']-.05
    assert planner.choose(obs)==(None,'mpc_wait')
    rope=dict(obs,terrain=None,rope=260.)
    assert MpcAvoider.recovery_needed(rope)==GroundReserve.recovery_needed(rope)
    assert MpcAvoider.reserve_cost(rope)==GroundReserve.reserve_cost(rope)
