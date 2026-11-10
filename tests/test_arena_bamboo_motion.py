"""Locked reticle timing is observable; initial locked age can be unknown."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_bamboo_motion import BambooClocks
from arena_vision import Box


def cue(phase,x=300,y=200,confidence=.9):
    return dict(box=Box(x-8,y-8,16,16),phase=phase,confidence=confidence)


def test_observed_aim_to_lock_supplies_a_future_attack_instead_of_marker_collision():
    clocks=BambooClocks()
    for t,phase in[(0.,'aim'),(.03,'aim'),(.06,'locked'),(.09,'locked')]:
        clocks.observe([cue(phase)],t)
    forecast,=clocks.forecasts(.09,-700.)
    assert forecast.fire_earliest==pytest.approx(1.)
    assert forecast.fire_latest==pytest.approx(1.10)
    assert forecast.future(.1).x>600  # The visible reticle is not a current hurt box.
    assert forecast.future(1.15).x<300
    assert forecast.at(.2).future(.4)==forecast.future(.6)


def test_missing_aim_onset_keeps_the_whole_possible_timer_interval():
    clocks=BambooClocks()
    for t in(1.,1.03,1.06):clocks.observe([cue('locked')],t)
    forecast,=clocks.forecasts(1.06,-700.)
    assert forecast.fire_latest-forecast.fire_earliest>=1.
    assert not clocks.forecasts(2.5,-700.)


def test_one_misclassified_frame_cannot_start_a_projectile_clock():
    clocks=BambooClocks()
    for t,phase in[(0.,'aim'),(.03,'locked'),(.06,'aim')]:clocks.observe([cue(phase)],t)
    assert not clocks.forecasts(.06,-700.)


def test_class_nms_duplicates_do_not_count_as_two_lock_observations():
    clocks=BambooClocks()
    clocks.observe([cue('aim'),cue('locked',confidence=.8)],0.)
    clocks.observe([cue('locked'),cue('locked',x=301,confidence=.8)],.03)
    assert not clocks.forecasts(.03,-700.)


def test_new_visible_positions_update_target_height_without_restarting_the_timer():
    clocks=BambooClocks()
    for t,phase in[(0.,'aim'),(.03,'aim'),(.06,'locked'),(.09,'locked')]:clocks.observe([cue(phase)],t)
    before,=clocks.forecasts(.09,-700.)
    for t in(.12,.15,.18):clocks.observe([cue('locked',y=204)],t)
    after,=clocks.forecasts(.18,-700.)
    assert (after.fire_earliest,after.fire_latest)==(before.fire_earliest,before.fire_latest)
    assert after.box.center[1]==pytest.approx(204.)


def test_unobserved_scroll_is_an_interval_instead_of_a_stationary_camera():
    clocks=BambooClocks()
    for t,phase in[(0.,'aim'),(.03,'aim'),(.06,'locked'),(.09,'locked')]:clocks.observe([cue(phase)],t)
    unknown,=clocks.forecasts(.09,None)
    still,=clocks.forecasts(.09,0.)
    moving,=clocks.forecasts(.09,-790.)
    envelope=unknown.future(1.3)
    for f in(still,moving):
        box=f.future(1.3)
        assert envelope.x<=box.x and envelope.x+envelope.w>=box.x+box.w
