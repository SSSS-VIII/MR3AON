"""Native-measured primitive/collider transitions, independent of CV/assets."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_motion import point,duration,DATA


def test_rope_transfer_restores_body_after_small_transition_collider():
    assert .24<duration('rope_down')<.29
    assert .21<duration('rope_up')<.26
    assert point('rope_down',.1)[4]==pytest.approx(.2,abs=.001)
    assert point('rope_down',1)[1]==pytest.approx(-1.5,abs=.001)
    assert point('rope_up',1)[1]==pytest.approx(1.5,abs=.001)
    assert point('rope_up',1)[4]==pytest.approx(.936,abs=.001)


def test_jump1_and_jump2_have_different_ascent_colliders():
    first=point('jump1',.1)
    second=point('jump2',.1)
    assert first[4]==pytest.approx(.624,abs=.001)
    assert first[2]==pytest.approx(.156,abs=.001)
    assert second[4]==pytest.approx(.2,abs=.001)
    assert point('jump2',.6)[4]==pytest.approx(.936,abs=.001)


def test_free_fall_tail_does_not_invent_ground_under_a_gap():
    assert point('jump1',1)[1]<point('jump1',.8)[1]
    assert DATA['profiles']['jump1']['tail_acceleration']==pytest.approx(-31.5,abs=.05)
    assert DATA['profiles']['jump2']['tail_acceleration']==pytest.approx(-34.3,abs=.05)
