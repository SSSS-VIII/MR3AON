"""Geometry/class similarity alone cannot establish gravity or a rebound."""
from collections import deque
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Track
from arena_object_motion import fit_ballistic


@pytest.mark.parametrize('velocity',[0.,35.,-200.])
def test_straight_motion_does_not_gain_fictitious_gravity(velocity):
    track=Track(1,Box(300,100,20,20),'pinball',.9,0)
    track.history=deque((i*.025,400-i*10,100+velocity*i*.025)for i in range(17))
    fit_ballistic(track,40)
    assert not track.ballistic


def test_visible_native_curvature_recovers_velocity_and_actual_floor_reference():
    track=Track(1,Box(300,100,20,20),'pinball',.9,0,floor_y=240)
    track.history=deque((i*.025,400-i*10,100-100*i*.025+.5*320*(i*.025)**2)for i in range(10))
    fit_ballistic(track,40)
    assert track.ballistic and track.vy==pytest.approx(-28)
    assert track.floor_y==240


def test_short_near_apex_window_does_not_override_native_ballistic_prior():
    track=Track(1,Box(300,100,20,20),'pinball',.9,0,floor_y=240)
    track.history=deque((i*.025,400-i*10,100+.5*320*(i*.025-.1)**2)for i in range(8))
    fit_ballistic(track,40)
    assert track.ballistic
