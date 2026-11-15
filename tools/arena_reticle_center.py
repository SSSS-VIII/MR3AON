"""Optional CPU reticle centers, independent of phase classification and clocks.

Pass the original detector boxes in their original order. Every input receives
one result; a rejected result has no refined center. Keep the original boxes
and cues for classification/tracking. This module does not modify either and
is not connected to the running detector, clock, or policy.

The reviewed 640x360 BGR prototype uses the original red star and ring. White
pixels can veto an ambiguous ring; they never propose an accepted center.
Native state, IDs, phases, and label geometry are not inputs.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import time

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / 'arena/vision-reticle-center.json'
TEMPLATE_SIZES = tuple(range(11, 30, 2))
MAX_CANDIDATES = 6


@dataclass(frozen=True)
class ReticleTexture:
    path: Path
    sha256: str

    @classmethod
    def from_config(cls, path=DEFAULT_CONFIG, *, root=ROOT):
        config = json.loads(Path(path).read_text())
        if config.get('version') != 1:
            raise ValueError('Expected reticle center asset configuration version 1')
        texture = config['texture']
        digest = texture['sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Reticle texture requires a lowercase SHA256')
        asset = Path(texture['path'])
        return cls(asset if asset.is_absolute() else Path(root) / asset, digest)


@dataclass(frozen=True)
class CenterResult:
    proposal_index: int
    center: tuple[float, float] | None
    reason: str | None
    evidence: dict = field(default_factory=dict)

    @property
    def accepted(self):
        return self.center is not None


def _tracking_box(box):
    """Copy geometry only; reproduce the reviewed clipped-circle correction.

    Kept local so this standalone module does not import or change BambooClocks.
    It matches arena_bamboo_motion.reticle_tracking_box, including HUD bounds.
    """
    if isinstance(box, Mapping):
        x, y, w, h = (float(box[k]) for k in ('x', 'y', 'w', 'h'))
    else:
        x, y, w, h = (float(getattr(box, k)) for k in ('x', 'y', 'w', 'h'))
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        raise ValueError('Reticle box must be finite with positive dimensions')
    if h < w and y <= 56:
        y, h = y + h - w, w
    elif h < w and y + h >= 359:
        h = w
    if not all(math.isfinite(v) for v in (x, y, w, h, x + w / 2, y + h / 2)):
        raise ValueError('Reticle box center must be finite')
    return x, y, w, h


class ReticleCenterRefiner:
    """Selective centers with explicit asset status and bounded per-ROI work.

    Asset bytes/SHA/decode are checked once at construction. Missing, changed,
    or invalid assets disable refinement: refine() still returns one rejection
    per input. There is no download, substitute texture, or per-frame file IO.
    Configuration syntax errors raise instead of silently changing the profile.

    last_stats contains CPU/wall milliseconds and actual ROI/template/ring work.
    This class does not set OpenCV process-wide threads or perform model inference.
    """

    def __init__(self, texture: ReticleTexture | None = None):
        texture = texture or ReticleTexture.from_config()
        self.asset_info = dict(path=str(texture.path), expected_sha256=texture.sha256,
                               actual_sha256=None, status='asset_missing')
        self.templates = []
        self.kernel = np.ones((3, 3), np.uint8)
        angles = (np.arange(12, dtype=np.float32) + .5) * (2 * np.pi / 12)
        self.radii = np.arange(5, 18.5, .5, dtype=np.float32)
        self.offsets = np.stack((self.radii[:, None] * np.cos(angles),
                                 self.radii[:, None] * np.sin(angles)), axis=-1)
        self.last_stats = self._stats()
        try:
            raw = Path(texture.path).read_bytes()
        except FileNotFoundError:
            return
        except OSError as error:
            self.asset_info.update(status='asset_unreadable', error=type(error).__name__)
            return
        digest = hashlib.sha256(raw).hexdigest()
        self.asset_info['actual_sha256'] = digest
        if digest != texture.sha256:
            self.asset_info['status'] = 'asset_hash_mismatch'
            return
        try:
            src = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
        except cv2.error:
            src = None
        if src is None:
            self.asset_info['status'] = 'asset_decode_failed'
            return
        if src.shape != (33, 34, 4):
            self.asset_info['status'] = 'asset_dimensions_mismatch'
            return
        f = src[:, :, :3].astype(np.float32) / 255.
        f = np.maximum(0, f[:, :, 2] - np.maximum(f[:, :, 0], f[:, :, 1])) * src[:, :, 3] / 255.
        h, w = f.shape
        center = ((w - 1) / 2, (h - 1) / 2)
        size = 49
        matrix = cv2.getRotationMatrix2D(center, 45., 1.)
        matrix[:, 2] += np.array([(size - 1) / 2 - center[0], (size - 1) / 2 - center[1]])
        rotated = cv2.warpAffine(f, matrix, (size, size), flags=cv2.INTER_LINEAR)
        self.templates = [(n, cv2.resize(rotated, (n, n), interpolation=cv2.INTER_AREA))
                          for n in TEMPLATE_SIZES]
        self.asset_info['status'] = 'ready'

    @staticmethod
    def _stats():
        return dict(cpu_ms=0., wall_ms=0., processed_rois=0, template_calls=0, ring_checks=0)

    @property
    def available(self):
        return self.asset_info['status'] == 'ready'

    def _ring(self, point, feature, x0, y0):
        self.last_stats['ring_checks'] += 1
        xx = (point['x'] - x0 - .5 + self.offsets[:, :, 0]).astype(np.float32)
        yy = (point['y'] - y0 - .5 + self.offsets[:, :, 1]).astype(np.float32)
        values = cv2.remap(feature, xx, yy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        # Eight weakest rays require a surrounding ring, not a few bright arms.
        strength = np.sort(values, axis=1)[:, :8].mean(axis=1)
        index = int(np.argmax(strength))
        return math.sqrt(max(0, point['star_score'] * float(strength[index]))), float(self.radii[index])

    def refine(self, bgr: np.ndarray, boxes: Sequence) -> list[CenterResult]:
        """Return aligned center estimates; raw boxes/cues remain caller-owned.

        Example: results = refiner.refine(bgr, [cue['box'] for cue in cues]).
        The original cues still supply the phase classifier's crops. A result
        with center=None is a reason to keep that original observation.
        """
        self.last_stats = self._stats()
        cpu, wall = time.process_time(), time.perf_counter()
        try:
            return self._refine(bgr, boxes)
        finally:
            self.last_stats.update(cpu_ms=(time.process_time() - cpu) * 1000,
                                   wall_ms=(time.perf_counter() - wall) * 1000)

    def _refine(self, bgr, boxes):
        if not boxes:
            return []
        if not self.available:
            return [CenterResult(i, None, self.asset_info['status'], dict(asset=self.asset_info.copy()))
                    for i in range(len(boxes))]
        if not isinstance(bgr, np.ndarray) or bgr.shape != (360, 640, 3) or bgr.dtype != np.uint8:
            raise ValueError('Reticle refinement requires a 640x360 uint8 BGR image')
        normalized, results = [], []
        for index, box in enumerate(boxes):
            try:
                normalized.append(_tracking_box(box))
                results.append(None)
            except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
                normalized.append(None)
                results.append(CenterResult(index, None, 'invalid_box'))
        for index, box in enumerate(normalized):
            if box is None:
                continue
            x, y, w, h = box
            cx, cy = x + w / 2, y + h / 2
            neighbors = [j for j, other in enumerate(normalized) if j != index and other is not None
                         and math.hypot(other[0] + other[2] / 2 - cx, other[1] + other[3] / 2 - cy)
                         < .5 * (min(other[2], other[3]) + min(w, h))]
            evidence = dict(tracking_box=box, neighboring_proposals=neighbors)
            if neighbors:
                results[index] = CenterResult(index, None, 'neighboring_proposal', evidence)
                continue
            search = min(14., max(5., min(w, h) * .35))
            # 20px covers the largest 18px ring plus dilation/interpolation.
            x0, x1 = max(0, int(cx - search - 20)), min(640, int(math.ceil(cx + search + 20)))
            y0, y1 = max(0, int(cy - search - 20)), min(360, int(math.ceil(cy + search + 20)))
            evidence.update(roi=(x0, y0, x1, y1), search_radius=search)
            if x1 <= x0 or y1 <= y0:
                results[index] = CenterResult(index, None, 'outside_image', evidence)
                continue
            self.last_stats['processed_rois'] += 1
            f = bgr[y0:y1, x0:x1].astype(np.float32) / 255.
            red = np.maximum(0, f[:, :, 2] - np.maximum(f[:, :, 0], f[:, :, 1]))
            red_ring = cv2.dilate(red, self.kernel)
            candidates = []
            for size, template in self.templates:
                if min(red.shape) < size:
                    continue
                self.last_stats['template_calls'] += 1
                score = cv2.matchTemplate(red, template, cv2.TM_CCORR_NORMED)
                yy, xx = np.indices(score.shape)
                px, py = xx + x0 + size / 2, yy + y0 + size / 2
                score[(abs(px - cx) > search) | (abs(py - cy) > search)] = -1
                maxima = (score >= cv2.dilate(score, self.kernel)) & (score > .3)
                iy, ix = np.nonzero(maxima)
                candidates.append(np.column_stack((px[iy, ix], py[iy, ix], score[iy, ix],
                                                    np.full(len(ix), size))))
            selected = []
            if candidates:
                peaks = np.concatenate(candidates)
                # Preserve the prototype's stable template/row/column tie order.
                # Dense/flat ROIs must not allocate a Python dict for each peak.
                for peak_index in np.argsort(-peaks[:, 2], kind='stable'):
                    px, py, star_score, size = peaks[peak_index]
                    if any(math.hypot(px - p['x'], py - p['y']) < 3 for p in selected):
                        continue
                    point = dict(x=float(px), y=float(py), star_score=float(star_score), size=int(size))
                    point['score'], point['radius'] = self._ring(point, red_ring, x0, y0)
                    selected.append(point)
                    if len(selected) == MAX_CANDIDATES:
                        break
            strong = [p for p in selected if p['score'] >= .6]
            weak = [p for p in selected if p['score'] >= .5]
            evidence.update(candidates=selected, confirmed_peaks=len(strong), weak_peaks=len(weak))
            if len(strong) != 1:
                results[index] = CenterResult(index, None, 'no_single_confirmed_peak', evidence)
                continue
            if len(weak) != 1:
                results[index] = CenterResult(index, None, 'secondary_red_peak', evidence)
                continue
            # White flash can only reveal ambiguity; it cannot add a new center.
            white = np.maximum(0, (np.minimum(f[:, :, 0], np.minimum(f[:, :, 1], f[:, :, 2])) - .5) * 2)
            any_ring = cv2.dilate(np.maximum(red, white), self.kernel)
            for point in selected:
                point['ambiguity_score'], point['ambiguity_radius'] = self._ring(point, any_ring, x0, y0)
            evidence['red_white_peaks'] = sum(p['ambiguity_score'] >= .5 for p in selected)
            if evidence['red_white_peaks'] != 1:
                results[index] = CenterResult(index, None, 'secondary_red_white_ring', evidence)
                continue
            best = strong[0]
            results[index] = CenterResult(index, (best['x'], best['y']), None, evidence)
        return results
