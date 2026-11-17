"""Static original projectile envelopes; no model, client or board access."""
from dataclasses import dataclass
from functools import cache
import json
from pathlib import Path

from arena_projection import SCALE


SOURCE=json.loads((Path(__file__).resolve().parents[1]/'arena/vision-bamboo-projectiles.json').read_text())


@dataclass(frozen=True)
class ProjectileEnvelope:
    spawn_left: float
    spawn_right: float
    width: float
    height: float
    retention_seconds: float


@cache
def projectile_envelope():
    """Contain every registered variant while retaining the ordinary head bound.

    spawn_left/right are possible *centers* of a minimum-width interval. The
    long laser's rear extends spawn_right; using its whole width around the
    ordinary bamboo center would incorrectly advance the leading edge.
    """
    scale=SOURCE['max_scale']
    variants=SOURCE['variants']
    left=min((v['center']['x']-v['size']['x']/2)*scale for v in variants)
    right=max((v['center']['x']+v['size']['x']/2)*scale for v in variants)
    half_height=max((abs(v['center']['y'])+v['size']['y']/2)*scale for v in variants)
    width=min(v['size']['x'] for v in variants)*scale*SCALE
    origin=640+SOURCE['spawn_offset_world']*SCALE
    edge_left=origin+left*SCALE
    edge_right=origin+right*SCALE
    retention=edge_right/(SOURCE['minimum_forward_speed_world']*SCALE)+SOURCE['retirement_slack_frames']/60
    return ProjectileEnvelope(edge_left+width/2,edge_right-width/2,width,
                              2*half_height*SCALE,retention)
