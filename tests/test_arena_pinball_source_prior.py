"""Constructor-complete priors stay optional and preserve observed physics."""
from collections import deque
from pathlib import Path
import json
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
pytest.importorskip('cv2')
from arena_object_motion import fit_ballistic,DATA
from arena_vision import Box,Track,Tracker,Detection


def descending(*,floor=250.):
    native=json.loads((Path(__file__).parent/'fixtures/arena-pinball-custom-parameters.json').read_text())['entry']['custom_parameters']
    acceleration=native['_acceleratedDown']*40
    history=[(i*.025,400-i*10,80+80*i*.025+.5*acceleration*(i*.025)**2)for i in range(10)]
    return Track(1,Box(300,history[-1][2]-10,20,20),'pinball',.9,history[-1][0],
                 history=deque(history),floor_y=floor,source_pinball_prior=True)


def test_native_default_descent_recovers_its_velocity_and_rebound_prior():
    track=descending();fit_ballistic(track,40)
    assert track.ballistic
    assert track.vy==pytest.approx(80+6*40*.225)
    assert (track.gravity_up,track.gravity_down,track.rebound_speed)==(400,240,200)
    # Legacy operation is preserved until the research factory opts in.
    assert (DATA['accelerated_up'],DATA['accelerated_down'],DATA['rebound_speed'])==(8,8,7)
    assert track.at(.01).source_pinball_prior


@pytest.mark.parametrize('velocity',[0.,35.,-200.])
def test_source_prior_does_not_override_long_observed_straight_motion(velocity):
    track=Track(1,Box(300,100,20,20),'pinball',.9,0,source_pinball_prior=True)
    track.history=deque((i*.025,400-i*10,100+velocity*i*.025)for i in range(17))
    fit_ballistic(track,40)
    assert not track.ballistic


def test_unknown_floor_stays_free_fall_with_the_source_prior():
    track=descending(floor=None);fit_ballistic(track,40)
    future=track.future(.2)
    expected=track.box.center[1]+track.vy*.2+.5*240*.2**2
    assert future.center[1]==pytest.approx(expected)
    assert track.floor_y is None


def test_tracker_applies_opt_in_only_to_new_pinball_tracks():
    for enabled in (False,True):
        tracker=Tracker(adaptive=True);tracker.source_pinball_prior=enabled
        result=tracker.update([Detection(Box(400,150,30,30),'pinball',.9),
                               Detection(Box(500,150,10,70),'trap',.9)],1.,(0.,0.))
        assert [t.source_pinball_prior for t in result]==[enabled,False]
