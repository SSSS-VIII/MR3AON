"""Continue measured horizontal scene flow through confirmed visual anchors.

Only recognition uses this flow. A track first needs independent scene motion;
fresh observations can then carry that evidence to overlapping static tracks.
"""
from statistics import median


class StaticAnchorFlow:
    def __init__(self):
        self.confirmed = {}
        self.time = None

    def observe(self, observation):
        now = observation.get('time')
        if now is None:
            return observation
        if self.time is not None and now < self.time:
            self.confirmed.clear()
        self.time = now
        fresh = [t for t in observation.get('tracks', []) if
            t.kind == 'trap' and t.collider_shape == 'BoxCollider' and t.observations >= 3
            and t.confidence >= .7 and 0 <= now-t.seen <= .1]
        self.confirmed = {key: value for key, value in self.confirmed.items() if 0 <= now-value[0] <= .18}
        independent = observation.get('scene_motion_observed') and observation.get('scene_velocity_x') is not None
        scene = observation.get('scene_velocity_x') if independent else None
        if scene is None:
            anchors = [t.vx for t in fresh if t.id in self.confirmed
                       and abs(t.vx-self.confirmed[t.id][1]) <= 45]
            if anchors and max(anchors)-min(anchors) <= 45:
                scene = median(anchors)
        if scene is None:
            return observation
        matched = []
        for track in fresh:
            if abs(track.vx-scene) > 45:
                continue
            x, y = track.box.center
            if any(d.kind == 'trap' and d.collider_shape == 'BoxCollider' and d.confidence >= .7
                   and abs(d.box.center[0]-x) <= 5 and abs(d.box.center[1]-y) <= 8
                   for d in observation.get('detections', [])):
                matched.append(track)
        # An old/predicted box alone cannot perpetuate a motion measurement.
        if not independent and not any(t.id in self.confirmed for t in matched):
            return observation
        for track in matched:
            self.confirmed[track.id] = (now, track.vx)
        if independent:
            return observation
        return dict(observation, scene_motion_observed=True, scene_velocity_x=scene,
                    fixed_recognition_motion_source='continued_visual_static_anchor')
