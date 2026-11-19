from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_input_transport import PROFILE, check_server_profile, repeat_failure, transport_action


def test_sender_constants_match_the_certified_pulse_profile():
    source=(Path(__file__).resolve().parents[1]/'arena/Capture/FrameServer.java').read_text()
    check_server_profile(source)
    with pytest.raises(ValueError):
        check_server_profile(source.replace('KEY_PULSE_MS = 80','KEY_PULSE_MS = 20'))


def test_same_key_needs_release_but_the_other_key_is_independent():
    previous=[dict(index=0,transport_action='jump',input_time=1.)]
    failure=repeat_failure(previous,'jump',1.05)
    assert failure['reason']=='input_transport_repeat_too_close'
    assert failure['gap_ms']==pytest.approx(50)
    assert repeat_failure(previous,'jump',1.1)is None
    assert repeat_failure(previous,'down',1.01)is None


def test_slide_and_air_down_share_the_s_key_and_its_longer_hold():
    assert transport_action('down','runOnGround: 5')=='slide'
    previous=[dict(index=0,transport_action='slide',input_time=1.),
              dict(index=1,transport_action='jump',input_time=1.2)]
    failure=repeat_failure(previous,'down',1.4)
    assert failure['previous_event']==0
    assert failure['minimum_gap_ms']==pytest.approx(500+1000/60)
    assert repeat_failure(previous,'down',1.55)is None
