"""Standalone CPU centers: raw crops survive, ambiguous/missing assets abstain."""
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
cv2 = pytest.importorskip('cv2')
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from arena_reticle_center import ReticleCenterRefiner, ReticleTexture, _tracking_box


@pytest.fixture
def texture(tmp_path):
    # Portable checksum/CPU-contract fixture, not a substitute game texture.
    rgba = np.zeros((33, 34, 4), np.uint8)
    cv2.line(rgba, (8, 8), (25, 25), (0, 0, 255, 255), 3)
    cv2.line(rgba, (8, 25), (25, 8), (0, 0, 255, 255), 3)
    path = tmp_path / 'synthetic-contract.png'
    assert cv2.imwrite(str(path), rgba)
    return ReticleTexture(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_config_is_relative_to_repository_and_pins_the_original_texture():
    texture = ReticleTexture.from_config()
    assert texture.path == ROOT / 'debug/arena-client/arena-entities/texture-previews/-1873529890869447913-point.png'
    assert texture.sha256 == '2d4cc4ecbb71394fa7c8d1bc288621615709a013d3dc909d83c27b278dcf8ee5'


def test_configuration_rejects_unversioned_or_unpinned_assets(tmp_path):
    path = tmp_path / 'config.json'
    for config in ({'version': 2}, {'version': 1, 'texture': {'path': 'x', 'sha256': 'unknown'}}):
        path.write_text(json.dumps(config))
        with pytest.raises(ValueError):
            ReticleTexture.from_config(path)


def test_missing_asset_returns_one_explicit_rejection_per_proposal_without_pixel_work(tmp_path, monkeypatch):
    refiner = ReticleCenterRefiner(ReticleTexture(tmp_path / 'missing.png', '0' * 64))
    monkeypatch.setattr(cv2, 'matchTemplate', lambda *a, **k: pytest.fail('Missing asset performed pixel work'))
    boxes = [dict(x=100, y=100, w=40, h=40), dict(x=200, y=100, w=40, h=40)]
    before = copy.deepcopy(boxes)
    results = refiner.refine(None, boxes)
    assert boxes == before and len(results) == len(boxes)
    assert [r.proposal_index for r in results] == [0, 1]
    assert all(r.center is None and r.reason == 'asset_missing' for r in results)
    assert refiner.last_stats['processed_rois'] == refiner.last_stats['template_calls'] == 0
    assert not refiner.available


def test_wrong_asset_hash_never_decodes_or_falls_back(texture, monkeypatch):
    monkeypatch.setattr(cv2, 'imdecode', lambda *a, **k: pytest.fail('Unverified bytes were decoded'))
    refiner = ReticleCenterRefiner(ReticleTexture(texture.path, '0' * 64))
    result, = refiner.refine(None, [dict(x=1, y=1, w=20, h=20)])
    assert result.reason == 'asset_hash_mismatch'
    assert result.evidence['asset']['actual_sha256'] == texture.sha256


@pytest.mark.parametrize('data,reason', [(b'not an image', 'asset_decode_failed'),
                                        (None, 'asset_dimensions_mismatch')])
def test_verified_but_invalid_asset_is_explicitly_unavailable(tmp_path, data, reason):
    if data is None:
        ok, encoded = cv2.imencode('.png', np.zeros((8, 8, 4), np.uint8))
        assert ok
        data = encoded.tobytes()
    path = tmp_path / 'invalid.png'
    path.write_bytes(data)
    refiner = ReticleCenterRefiner(ReticleTexture(path, hashlib.sha256(data).hexdigest()))
    assert refiner.asset_info['status'] == reason and not refiner.available


@pytest.mark.parametrize('box,expected', [
    (dict(x=10, y=55, w=40, h=10), (10, 25, 40, 40)),
    (dict(x=10, y=340, w=40, h=20), (10, 340, 40, 40)),
    (dict(x=10, y=100, w=40, h=20), (10, 100, 40, 20)),
])
def test_clipped_circle_geometry_is_a_copy_and_matches_existing_rule(box, expected):
    from arena_bamboo_motion import reticle_tracking_box
    from arena_vision import Box
    before = box.copy()
    assert _tracking_box(box) == expected
    assert tuple(asdict(reticle_tracking_box(Box(**box))).values()) == expected
    assert box == before


def test_bad_boxes_keep_order_and_do_not_hide_other_observations(texture):
    refiner = ReticleCenterRefiner(texture)
    boxes = [dict(x=float('nan'), y=20, w=30, h=30), dict(x=100, y=100, w=30, h=30),
             dict(x=0, y=0, w=-1, h=20), dict(x=2000, y=20, w=30, h=30)]
    results = refiner.refine(np.zeros((360, 640, 3), np.uint8), boxes)
    assert [r.proposal_index for r in results] == list(range(4))
    assert [r.reason for r in results] == ['invalid_box', 'no_single_confirmed_peak',
                                          'invalid_box', 'outside_image']


def test_only_reviewed_bgr_plane_is_accepted(texture):
    refiner = ReticleCenterRefiner(texture)
    for image in (np.zeros((720, 1280, 3), np.uint8), np.zeros((360, 640), np.uint8),
                  np.zeros((360, 640, 3), np.float32)):
        with pytest.raises(ValueError, match='640x360 uint8 BGR'):
            refiner.refine(image, [dict(x=100, y=100, w=40, h=40)])


def test_empty_and_neighboring_proposals_do_not_pay_template_cost(texture, monkeypatch):
    refiner = ReticleCenterRefiner(texture)
    monkeypatch.setattr(cv2, 'matchTemplate', lambda *a, **k: pytest.fail('Rejected before template search'))
    monkeypatch.setattr(cv2, 'dilate', lambda *a, **k: pytest.fail('Rejected before ring work'))
    assert refiner.refine(None, []) == []
    boxes = [dict(x=100, y=100, w=40, h=40), dict(x=108, y=103, w=40, h=40)]
    results = refiner.refine(np.zeros((360, 640, 3), np.uint8), boxes)
    assert [r.reason for r in results] == ['neighboring_proposal'] * 2
    assert [r.evidence['neighboring_proposals'] for r in results] == [[1], [0]]
    assert refiner.last_stats['processed_rois'] == refiner.last_stats['ring_checks'] == 0


def test_cpu_work_stays_local_and_assets_are_loaded_once(texture, monkeypatch):
    refiner = ReticleCenterRefiner(texture)
    original = cv2.matchTemplate
    shapes = []
    def match(image, template, method):
        shapes.append(image.shape)
        return original(image, template, method)
    monkeypatch.setattr(cv2, 'matchTemplate', match)
    monkeypatch.setattr(Path, 'read_bytes', lambda *a, **k: pytest.fail('Per-frame asset IO'))
    # A flat red image creates dense correlation plateaus, not just easy black ROIs.
    image = np.zeros((360, 640, 3), np.uint8)
    image[:, :, 2] = 255
    image.setflags(write=False)
    boxes = [dict(x=70 * i + 30, y=150, w=32, h=32) for i in range(6)]
    results = refiner.refine(image, boxes)
    assert len(results) == len(boxes)
    assert refiner.last_stats['processed_rois'] == 6
    assert refiner.last_stats['template_calls'] == len(shapes) == 60
    assert all(max(shape) <= 69 for shape in shapes)
    assert refiner.last_stats['ring_checks'] <= 12 * 6
    assert all(len(r.evidence.get('candidates', [])) <= 6 for r in results)
    assert refiner.last_stats['cpu_ms'] >= 0 and refiner.last_stats['wall_ms'] >= 0


PIXEL_CASES = json.loads((ROOT / 'tests/fixtures/arena-reticle-centers.json').read_text())['cases']


@pytest.mark.parametrize('case', PIXEL_CASES, ids=lambda case: case['name'])
def test_frozen_original_pixels_preserve_raw_classifier_boxes(case):
    texture = ReticleTexture.from_config()
    image_path = ROOT / case['image']
    if not texture.path.is_file() or not image_path.is_file():
        pytest.skip('Original local client texture/screenshots are intentionally not distributed in Git')
    assert hashlib.sha256(image_path.read_bytes()).hexdigest() == case['sha256']
    refiner = ReticleCenterRefiner(texture)
    assert refiner.available
    image = cv2.imread(str(image_path))
    image.setflags(write=False)
    # Metadata remains caller-owned; only the geometry list enters the module.
    cues = [dict(box=SimpleNamespace(**box), phase=('aim', 'locked', 'uncertain')[i % 3],
                 confidence=.9, id=1000 + i) for i, box in enumerate(case['boxes'])]
    before = copy.deepcopy(cues)
    results = refiner.refine(image, [cue['box'] for cue in cues])
    assert cues == before and len(results) == len(cues)
    actual = [dict(center=list(r.center) if r.accepted else None, reason=r.reason) for r in results]
    assert actual == case['expected']
    assert [r.proposal_index for r in results] == list(range(len(cues)))
