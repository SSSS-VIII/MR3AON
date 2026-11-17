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


def retag_laser_targets(raw, targets, profile):
    """Optional offline native-label subtype; never infer an actor's family.

    Match the registered original local collider, then only change the class
    of its existing visible quad. Keep geometry and other labels unchanged.
    """
    part=profile.get('separate_bamboo_laser')
    if not part:return targets
    import numpy as np
    from arena_native_json import normalize_arrays
    from arena_yolo_obb_data import collider_quad,visible_quad
    index=part['physical_class']
    meta=profile['classes'][index]
    if meta.get('resource')!='EnemyFlyBamboo' or meta.get('source_part')!='laser_attack':
        raise ValueError('Laser subtype does not identify the reviewed source collider')
    laser=next(v for v in SOURCE['variants'] if v['name']=='Laser')
    quads=[]
    for obj in normalize_arrays(raw).get('objects') or []:
        if obj.get('type')!='EnemyFlyBamboo' or obj.get('dead') or not obj.get('renderers'):continue
        for collider in obj.get('colliders') or []:
            if collider.get('type')!='BoxCollider' or collider.get('name')!='Attack':continue
            if not all(abs(collider.get(key,{}).get(axis,float('inf'))-laser[key][axis])<1e-6
                       for key in ('size','center') for axis in ('x','y','z')):continue
            quad=visible_quad(collider_quad(collider))
            if quad is not None:quads.append(quad)
    result=[]
    for cls,quad in targets:
        matched=any(np.allclose(quad,np.roll(q,k,axis=0),atol=1e-5,rtol=0)
                    for original in quads for q in (original,original[::-1]) for k in range(4))
        result.append((index if matched else cls,quad))
    return result
