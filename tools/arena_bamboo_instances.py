"""Associate stock pose marker instances with a second visual phase head."""
from copy import deepcopy
import math

from arena_bamboo_point import normalized_box, rectangle_iou
from arena_vision import Box


def pose_phase_agreement(cue):
    """Only explicit, reviewed two-head evidence confirms an instance phase."""
    if cue.get('pose_instance') is not True or cue.get('phase') not in ('aim', 'locked'):
        return False
    field = cue.get('center_refinement')
    if (not isinstance(field, dict) or field.get('version') != 1
            or field.get('space') != 'screen_640x360' or field.get('reason') is not None):
        return False
    evidence = field.get('evidence')
    if (not isinstance(evidence, dict) or evidence.get('source') != 'stock_pose_two_head_instance'
            or evidence.get('phase') != cue['phase']):
        return False
    heads = evidence.get('supporting_heads')
    if not isinstance(heads, list) or not heads or any(h not in ('obb', 'local_phase') for h in heads):
        return False
    values = [evidence.get(k) for k in ('pose', 'corroboration', 'visibility')]
    return all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) and v >= .8 for v in values)


def expand_bamboo_instances(cues, predictions):
    """Keep distinct point proposals; never use native states or identities."""
    if len(cues) != len(predictions):
        raise ValueError('Each bamboo cue needs its own prediction group')
    proposed, fallback = [], []
    for cue, outputs in zip(cues, predictions):
        c = deepcopy(cue)
        if isinstance(c['box'], dict):
            c['box'] = Box(**c['box'])
        try:
            x, y, w, h = normalized_box(c['box'])
        except (ValueError, AttributeError, TypeError, OverflowError):
            fallback.append(c)
            continue
        box = c['box']
        parent = [box.x, box.y, box.x + box.w, box.y + box.h]
        found = False
        for p in outputs:
            if not all(math.isfinite(v) for v in (*p['point'], *p['box'], p['confidence'])):
                continue
            px, py, visibility = p['point']
            phase = p['phase']
            support = {}
            if c.get('obb_phase') == phase:
                support['obb'] = c['confidence']
            local = c.get('phase_scores', {}).get(phase, 0)
            if local >= .8:
                support['local_phase'] = local
            support = {head: score for head, score in support.items() if score >= .8}
            corroboration = max(support.values(), default=0.)
            if (phase not in ('aim', 'locked') or p['confidence'] < .8 or visibility < .8
                    or corroboration < .8 or not (0 <= px <= 640 and 55 <= py <= 360)
                    or not (p['box'][0] <= px <= p['box'][2] and p['box'][1] <= py <= p['box'][3])
                    or math.dist((px, py), (x + w / 2, y + h / 2)) > 32
                    or rectangle_iou(p['box'], parent) < .3):
                continue
            width, height = p['box'][2] - p['box'][0], p['box'][3] - p['box'][1]
            if min(width, height) <= 0:
                continue
            diameter = max(width, height)
            # Full point-centered circles must not be re-normalized as partial
            # boxes at the HUD edge. These boxes are cues, never hurt colliders.
            item = dict(c, box=Box(px - diameter / 2, py - diameter / 2, diameter, diameter),
                        phase=phase, confidence=min(p['confidence'], corroboration),
                        pose_instance=True, pose_corroborated=True,
                        center_refinement=dict(version=1, space='screen_640x360', reason=None,
                            center=[px, py], evidence=dict(source='stock_pose_two_head_instance',
                                phase=phase, pose=p['confidence'], visibility=visibility,
                                corroboration=corroboration, supporting_heads=sorted(support))))
            proposed.append(item)
            found = True
        if not found:
            fallback.append(c)
    kept = []
    for c in sorted(proposed, key=lambda c: c['confidence'], reverse=True):
        if any(c['phase'] == other['phase'] and math.dist(c['box'].center, other['box'].center) < 3
               for other in kept):
            continue
        kept.append(c)
    return kept + fallback
