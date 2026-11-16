"""Continue the last measured physical fit, not a secant through an impact."""
from pathlib import Path
import sys,json
from collections import deque
from copy import deepcopy
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Track,Tracker,Detection
from arena_object_motion import fit_ballistic
from arena_projection import SCALE

DATA=json.loads((Path(__file__).parent/'fixtures/arena-pinball-rebound-carry.json').read_text())


def sample(case):
    kw=deepcopy(case['track']);kw['box']=Box(**kw['box'])
    for field in('history','angular_history','rush_history','confidence_history'):
        kw[field]=deque(kw[field],maxlen=64)
    track=Track(**kw)
    # The generic regression at an impact can legitimately have zero slope.
    # The last mature physical fit remains independent stored evidence.
    track.vy=0.;track.ballistic=False;track.pinball_carry_active=False
    return track


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['episode'])
def test_original_future_displacement_after_a_visual_rebound(case):
    track=sample(case);prior=deepcopy(track.pinball_fit)
    fit_ballistic(track,SCALE)
    assert track.ballistic and track.pinball_carry_active
    assert track.pinball_fit==prior
    predicted=track.future(case['truth']['horizon']).center[1]-track.box.center[1]
    error=predicted-case['truth']['native_delta']
    assert error==pytest.approx(case['truth']['error'],abs=1e-8)
    assert abs(error)<abs(case['old_error'])
    assert track.at(.04).pinball_rebound_carry


@pytest.mark.parametrize('reason',['disabled','no_fit','stale','no_old_floor','no_current_floor','position_disagrees'])
def test_no_rebound_is_invented_without_recent_matching_measured_evidence(reason):
    track=sample(DATA['cases'][0])
    if reason=='disabled':track.pinball_rebound_carry=False
    elif reason=='no_fit':track.pinball_fit=None
    elif reason=='stale':track.pinball_fit['seen']-=1.
    elif reason=='no_old_floor':track.pinball_fit['floor_y']=None
    elif reason=='no_current_floor':track.floor_y=None
    else:track.box.y-=100.
    fit_ballistic(track,SCALE)
    assert not track.ballistic and not track.pinball_carry_active
    assert track.vy==0.


def test_internal_candidate_is_off_and_only_applies_to_pinball_tracks():
    tracker=Tracker(adaptive=True)
    assert not tracker.pinball_rebound_carry
    tracker.pinball_rebound_carry=True
    tracks=tracker.update([Detection(Box(300,100,12,12),'pinball',.9),
                           Detection(Box(400,100,12,12),'trap',.9)],1.,(0.,0.))
    assert next(t for t in tracks if t.kind=='pinball').pinball_rebound_carry
    assert not next(t for t in tracks if t.kind=='trap').pinball_rebound_carry
