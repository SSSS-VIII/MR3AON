"""A walked-off edge must not disable the original first-jump escape."""
from pathlib import Path
import copy,json,sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box
from arena_mpc import MpcAvoider

class GroundRecovery(MpcAvoider):
    ground_reserve_recovery=True
    ground_static_search=True
    ordinary_air_down_gap=.04

def observed_fall():
    obs=copy.deepcopy(json.loads((Path(__file__).parent/'fixtures/arena-unspent-ground-fall.json').read_text())['observation'])
    obs['player']=Box(**obs['player'])
    return obs

def test_preserved_first_jump_is_used_to_escape_below_visible_platform():
    obs=observed_fall();policy=GroundRecovery()
    assert obs['jumps']==0 and obs['terrain']['at_player']
    assert obs['player'].y>obs['terrain']['y']+35
    assert policy.uses_search(obs)
    assert policy.choose(obs)==('jump','mpc_jump1')

def test_disabled_research_option_preserves_clear_fallback():
    obs=observed_fall();policy=MpcAvoider()
    assert not policy.recovery_needed(obs)and not policy.uses_search(obs)
    assert policy.choose(obs)==(None,'clear')

def test_grounded_safe_role_does_not_trigger_fall_recovery():
    obs=observed_fall();obs['phase']='ground';obs['player'].y=obs['terrain']['y']-obs['player'].h
    policy=GroundRecovery()
    assert not policy.recovery_needed(obs)and not policy.uses_search(obs)
    assert policy.choose(obs)==(None,'clear')

def test_unconfirmed_support_does_not_claim_a_recovery_route():
    obs=observed_fall();obs['terrain']=None
    assert not GroundRecovery.recovery_needed(obs)
