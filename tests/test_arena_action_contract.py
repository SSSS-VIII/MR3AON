"""Ground contact alone cannot prove that an original slide input took effect."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_action_contract import contract,effect_matches,meaningful,prerequisite


def test_slide_requires_a_real_ground_running_to_sliding_transition():
    expected=contract('runOnGround: 5','down','slideOnGround: 7')
    assert meaningful(expected)
    assert prerequisite(expected,'runOnGround: 5')
    assert not prerequisite(expected,'slideOnGround: 7')
    assert effect_matches(expected,'slideOnGround: 7')
    assert not effect_matches(expected,'runOnGround: 5')
    assert not meaningful(contract('runOnGround: 5','down','runOnGround: 5'))


def test_completed_transfers_still_accept_the_original_intermediate_state():
    down=contract('runOnLine: 1','down','runOnLineDown: 2')
    assert effect_matches(down,'rollToLineDown: 3')
    assert effect_matches(down,'runOnLineDown: 2')
    up=contract('runOnLineDown: 2','jump','runOnLine: 1')
    assert effect_matches(up,'rollToLineOn: 4')
    assert effect_matches(up,'runOnLine: 1')


def test_native_landing_then_first_jump_is_not_an_ignored_air_input():
    # v17 window 9, frame 699: all three trials restore the same native parent.
    # none lands at y=-.1300049; jump enters jump:14 at y=-.0467033, HP5000.
    expected=contract('fall: 15','jump','jump: 14')
    assert meaningful(expected)
    assert prerequisite(expected,'fall: 15')
    assert effect_matches(expected,'jump: 14')
    # Neither an ignored key nor its no-input landing proves this effect.
    assert not effect_matches(expected,'fall: 15')
    assert not effect_matches(expected,'runOnGround: 5')
    # The same coarse air/one-jump pose while still rising is not its entry.
    assert not prerequisite(expected,'jump: 14')
    assert not meaningful(contract('fall: 15','jump','fall: 15'))
