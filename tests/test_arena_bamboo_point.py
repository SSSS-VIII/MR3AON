"""A point estimate must never erase an already predicted bamboo hazard."""
from copy import deepcopy
from pathlib import Path
from statistics import median
import math
import random
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from arena_bamboo_point import (
    normalized_box, point_y, point_bounds, refine_point_cue, remember_point_interval,
    target_envelope,
)
from arena_vision import Box


def cue(phase='locked', box=None):
    return dict(box=box or Box(292, 192, 16, 16), phase=phase,
                confidence=.95, motion_kind='bamboo')


def prediction(x=300., y=201., phase='locked', confidence=.95, visibility=.99):
    return dict(box=[292., 192., 308., 208.], phase=phase,
                confidence=confidence, point=[x, y, visibility])


def test_point_keeps_original_proposal_and_phase_without_mutation():
    original = cue()
    before = deepcopy(original)
    result = refine_point_cue(original, [prediction()])
    assert original == before
    assert {k: v for k, v in result.items() if k != 'center_refinement'} == original
    assert result['center_refinement']['center'] == [300., 201.]
    assert point_y(result, 17.) == 184.


@pytest.mark.parametrize('bad', [
    dict(phase='aim'), dict(confidence=.79), dict(visibility=.79),
    dict(x=309.), dict(y=float('nan')),
])
def test_wrong_phase_weak_or_distant_point_abstains(bad):
    result = refine_point_cue(cue(), [prediction(**bad)])
    assert result['center_refinement']['center'] is None
    assert point_y(result, 17.) == 183.


def test_nearby_distinct_points_abstain_even_with_high_visibility():
    result = refine_point_cue(cue(), [prediction(y=198.), prediction(y=203.)])
    assert result['center_refinement']['reason'] == 'ambiguous_points'
    # Visibility alone cannot distinguish the two actual target centers.
    assert point_y(result, 0.) == 200.
    assert point_bounds(result, 17.) == (181., 186.)


def test_duplicate_predictions_of_same_point_are_not_distinct_targets():
    result = refine_point_cue(cue(), [prediction(), prediction(y=201.5)])
    assert result['center_refinement']['center'] == [300., 201.]


@pytest.mark.parametrize('field', [
    None, {}, dict(version=2),
    dict(version=1, space='world', center=[300., 201.]),
    dict(version=1, space='screen_640x360', center=[300., 201.], reason='rejected'),
    dict(version=1, space='screen_640x360', center=[300., math.inf]),
    dict(version=1, space='screen_640x360', center=[True, 201.]),
    dict(version=1, space='screen_640x360', center=[300., 361.]),
])
def test_malformed_optional_evidence_preserves_baseline(field):
    assert point_y(dict(cue(), center_refinement=field), 30.) == 170.


def test_clipped_circular_marker_uses_unclipped_center_for_selection():
    assert normalized_box(Box(292, 55, 16, 8)) == (292, 47, 16, 16)
    assert normalized_box(Box(292, 352, 16, 8)) == (292, 352, 16, 16)
    with pytest.raises(ValueError):
        normalized_box(Box(292, 192, 0, 16))


def test_rolling_interval_contains_original_and_point_medians_on_both_sides():
    rng = random.Random(260)
    clock = {}
    originals, points = [], []
    for _ in range(300):
        baseline = rng.uniform(-200, 400)
        point = baseline + rng.uniform(-8, 8)
        originals = (originals + [baseline])[-3:]
        points = (points + [point])[-3:]
        remember_point_interval(clock, baseline, point)
        clock['target_y'] = median(originals)
        center, height = target_envelope(clock, 4.)
        for target in (median(originals), median(points)):
            assert center - height / 2 <= target - 2. + 1e-10
            assert center + height / 2 >= target + 2. - 1e-10
        assert len(clock['point_low_samples']) <= 3


def test_linked_actual_flight_replaces_uncertainty_with_original_flight_fit():
    clock = dict(target_y=200., attack_id=7)
    remember_point_interval(clock, 200., 208.)
    assert target_envelope(clock, 4.) == (200., 4.)


def test_no_point_or_invalid_history_does_not_change_hazard():
    clock = dict(target_y=200.)
    assert target_envelope(clock, 4.) == (200., 4.)
    remember_point_interval(clock, 200., 200.)
    assert target_envelope(clock, 4.) == (200., 4.)
    remember_point_interval(clock, math.nan, 204.)
    assert target_envelope(clock, 4.) == (200., 4.)


def test_stateful_point_envelopes_keep_identity_launch_and_original_future_boxes():
    from arena_bamboo_motion import BambooClocks
    old, candidate = BambooClocks(), BambooClocks()
    candidate.point_uncertainty = True
    for index in range(12):
        stamp, camera = index * .03, index * .7
        phase = 'aim' if index < 2 else 'locked'
        raw = cue(phase, Box(292, 192 + camera, 16, 16))
        refined = dict(raw, center_refinement=dict(
            version=1, space='screen_640x360', reason=None,
            center=[300., 200. + camera + (-5 if index % 2 else 6)],
        ))
        old.observe([raw], stamp, camera)
        candidate.observe([refined], stamp, camera)
        baseline = old.forecasts(stamp, -700., camera)
        envelopes = candidate.forecasts(stamp, -700., camera)
        assert len(baseline) == len(envelopes)
        for before, after in zip(baseline, envelopes):
            assert (before.id, before.fire_earliest, before.fire_latest) == (
                after.id, after.fire_earliest, after.fire_latest)
            for future in (0., .2, .4):
                a, b = before.future(future), after.future(future)
                assert (a.x, a.w) == (b.x, b.w)
                assert b.y <= a.y + 1e-9
                assert b.y + b.h >= a.y + a.h - 1e-9
    # Association and flight matching continue to use the original target.
    for identity, clock in old.clocks.items():
        assert candidate.clocks[identity]['target_y'] == clock['target_y']


def test_perception_enables_interval_only_with_explicit_point_detector():
    from arena_obb_detector import ObbPerception

    class Detector:
        profile = dict(classes=[dict(motion_kind='bamboo')])

    assert ObbPerception(Detector()).bamboo_clocks.point_uncertainty is False
    detector = Detector()
    detector.point_refiner = object()
    assert ObbPerception(detector).bamboo_clocks.point_uncertainty is True


def test_roi_batches_keep_half_pixel_origin_order_and_non_bamboo_cues():
    import numpy as np
    from types import SimpleNamespace
    from arena_bamboo_point import BambooPointRefiner

    class Tensor:
        def __init__(self, data):
            self.data = np.asarray(data)

        def cpu(self):
            return self

        def numpy(self):
            return self.data

    batches = []

    class Model:
        names = {0: 'aim', 1: 'locked'}

        def predict(self, images, **options):
            batches.append(len(images))
            return [SimpleNamespace(
                boxes=SimpleNamespace(xyxy=Tensor([[23.5, 23.5, 39.5, 39.5]]),
                                      cls=Tensor([1]), conf=Tensor([.95])),
                keypoints=SimpleNamespace(data=Tensor([[[31.5, 31.5, .99]]])),
            ) for _ in images]

    refiner = BambooPointRefiner.__new__(BambooPointRefiner)
    refiner.model, refiner.options = Model(), {}
    refiner.dummy = np.full((64, 64, 3), 114, np.uint8)
    cues = [cue(box=Box(100 + i, 192, 16, 16)) for i in range(35)]
    other = dict(motion_kind='arrow', box=Box(200, 100, 10, 10))
    cues.insert(5, other)
    results = refiner.refine(np.zeros((360, 640, 3), np.uint8), cues)
    assert batches == [32, 4]
    assert results[5] is other
    for original, result in zip(cues, results):
        if original is other:
            continue
        assert result['center_refinement']['center'] == list(original['box'].center)
    assert refiner.last_stats['rois'] == refiner.last_stats['accepted'] == 35


def test_roi_refiner_rejects_wrong_screenshot_geometry_before_inference():
    import numpy as np
    from arena_bamboo_point import BambooPointRefiner

    refiner = BambooPointRefiner.__new__(BambooPointRefiner)
    with pytest.raises(ValueError, match='640x360'):
        refiner.refine(np.zeros((360, 640, 4), np.uint8), [])


def test_stock_pose_warmup_retains_overlapping_boxes_for_point_selection(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import arena_yolo
    from arena_bamboo_point import BambooPointRefiner

    weights = tmp_path / 'weights' / 'best.pt'
    weights.parent.mkdir()
    weights.write_bytes(b'fake model; the test substitutes the stock loader')
    (tmp_path / 'profile.json').write_text(json.dumps(dict(
        task='pose', crop_px=64, imgsz=192, kpt_shape=[1, 3], classes=['aim', 'locked'],
    )))
    calls = []

    class Model:
        task = 'pose'
        names = {0: 'aim', 1: 'locked'}

        def predict(self, images, **options):
            calls.append((len(images), options))
            return []

    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setattr(arena_yolo, 'offline_sdk', lambda: SimpleNamespace(YOLO=lambda _: Model()))
    refiner = BambooPointRefiner(weights)
    assert [count for count, _ in calls] == [1, 2, 4, 8, 16, 32]
    assert all(options['iou'] == .95 for _, options in calls)
    assert refiner.options['iou'] == refiner.info['nms_iou'] == .95
    # Overlapping full-ring boxes remain separate until this point check.
    result = refine_point_cue(cue(), [prediction(y=196.), prediction(y=204.)])
    assert result['center_refinement']['reason'] == 'ambiguous_points'


@pytest.mark.parametrize('candidates', [None, [True], [[300., math.nan]], [[300., 230.]], [[True, 200.]]])
def test_malformed_or_distant_ambiguous_candidates_keep_original_bounds(candidates):
    ambiguous = dict(cue(), center_refinement=dict(
        version=1, space='screen_640x360', reason='ambiguous_points',
        evidence=dict(candidates=candidates), center=None,
    ))
    assert point_bounds(ambiguous, 17.) == (183., 183.)


def test_stateful_ambiguous_ownership_keeps_both_points_and_original_clock():
    from arena_bamboo_motion import BambooClocks
    clock = BambooClocks()
    clock.point_uncertainty = True
    for index, phase in enumerate(('aim', 'aim', 'locked', 'locked')):
        raw = cue(phase)
        candidates = [prediction(y=196., phase=phase), prediction(y=204., phase=phase)]
        refined = refine_point_cue(raw, candidates)
        assert refined['center_refinement']['center'] is None
        clock.observe([refined], index * .03)
    forecast, = clock.forecasts(.09, -700.)
    from arena_projection import SCALE
    for target in (196., 200., 204.):
        box = forecast.future(.2)
        # Even the original unscaled collider around either candidate fits.
        assert box.y <= target - .1 * SCALE + 1e-9
        assert box.y + box.h >= target + .1 * SCALE - 1e-9
