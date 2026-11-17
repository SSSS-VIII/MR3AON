"""Earlier causal curve evidence must retain rejection and phase semantics."""
from collections import deque
import json
from pathlib import Path

import pytest

from arena_vision import Box, Detection, Track, Tracker


def make_track(enabled=False, kind='eye_enemy'):
    return Track(1, Box(0, 0, 20, 20), kind, 1, 0,
                 adaptive_velocity=True, early_sine_motion=enabled,
                 history=deque(maxlen=64))


def feed(track, samples, confidence=.98, reference=(0., 0.)):
    for stamp, x, y in samples:
        track.update(Detection(Box(x-10, y-10, 20, 20), track.kind,
                               confidence, attack_phase='normal'),
                     stamp, reference)
    return track


def test_real_pre_hit_pixels_forecast_held_out_next_exposure():
    data=json.loads((Path(__file__).parent/'fixtures/arena-short-curve-pixels.json').read_text())
    old=feed(make_track(), data['samples'][:-1], data['confidence'])
    new=feed(make_track(True), data['samples'][:-1], data['confidence'])
    stamp, _, truth=data['samples'][-1]
    assert old.sine_count==0
    assert new.sine_count>=2
    assert abs(new.future(stamp-new.seen).center[1]-truth)<1.1
    assert abs(old.future(stamp-old.seen).center[1]-truth)>2.7
    # Advancing to a delayed decision must rotate the fitted phase, so the
    # same absolute future does not change with the projection split.
    assert new.at(.035).future(.12).center==pytest.approx(new.future(.155).center)


def test_first_fit_alone_does_not_confirm_a_curve():
    data=json.loads((Path(__file__).parent/'fixtures/arena-short-curve-pixels.json').read_text())
    track=feed(make_track(True), data['samples'][:6])
    assert track.sine_count==1
    assert track.at(.04).sine_count==1
    expected=track.box.center[1]+track.vy*.04
    assert track.future(.04).center[1]==pytest.approx(expected)


def test_short_samples_do_not_manufacture_sine_from_straight_motion_or_noise():
    straight=[[i*.07, 600-i*50, 160+i*4] for i in range(8)]
    assert feed(make_track(True), straight).sine_count==0
    noisy=[[i*.07, 600-i*50, 160+offset]
           for i,offset in enumerate([0, 15, -12, 18, -17, 24, -24, 20])]
    assert feed(make_track(True), noisy).sine_count==0


def test_short_fit_is_not_enabled_for_other_visual_families_or_weak_pixels():
    data=json.loads((Path(__file__).parent/'fixtures/arena-short-curve-pixels.json').read_text())
    assert feed(make_track(True, 'trap'), data['samples']).sine_count==0
    assert feed(make_track(True), data['samples'], .69).sine_count==0


def test_tracker_propagates_research_flag_without_changing_default_tracks():
    detection=Detection(Box(400, 160, 20, 20), 'eye_enemy', .98)
    old=Tracker(adaptive=True)
    new=Tracker(adaptive=True)
    new.early_sine_motion=True
    assert not old.update([detection], 1., (0., 0.))[0].early_sine_motion
    assert new.update([detection], 1., (0., 0.))[0].early_sine_motion
