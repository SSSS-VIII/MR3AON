from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_fixed_static_flow import StaticAnchorFlow
from arena_vision import Box,Detection


def observation(now, *, independent=False, identities=(1,)):
    tracks=[SimpleNamespace(id=i,kind='trap',collider_shape='BoxCollider',observations=4,
        confidence=.9,seen=now,box=Box(100*i,150,12,80),vx=-740) for i in identities]
    return dict(time=now,scene_motion_observed=independent,scene_velocity_x=-741,
        tracks=tracks,detections=[Detection(t.box,'trap',.9,collider_shape='BoxCollider')for t in tracks])


def test_unknown_boxes_cannot_bootstrap_flow_without_independent_evidence():
    flow=StaticAnchorFlow()
    for t in (0,.04,.08):
        obs=observation(t)
        assert flow.observe(obs) is obs and not flow.confirmed


def test_fresh_anchor_carries_flow_to_overlapping_track_without_mutating_raw_motion():
    flow=StaticAnchorFlow();first=observation(0,independent=True)
    assert flow.observe(first) is first
    raw=observation(.04,identities=(1,2));saved=deepcopy(raw)
    enriched=flow.observe(raw)
    assert enriched['scene_motion_observed'] and enriched['scene_velocity_x']==-740
    assert raw==saved and not raw['scene_motion_observed']
    # The next anchor was seen alongside an independently grounded one.
    assert set(flow.confirmed)=={1,2}
    assert flow.observe(observation(.08,identities=(2,)))['scene_motion_observed']


def test_prediction_disappearance_reversal_and_track_id_reuse_do_not_keep_flow_alive():
    for change in ('missing_detection','stale','changed_velocity','reused','predicted_box'):
        flow=StaticAnchorFlow();flow.observe(observation(0,independent=True))
        raw=observation(.04)
        if change=='missing_detection':raw['detections']=[]
        elif change=='stale':raw['tracks'][0].seen=-1
        elif change=='changed_velocity':raw['tracks'][0].vx=-1200
        elif change=='reused':raw['time']=.3;raw['tracks'][0].seen=.3
        else:raw['tracks'][0].box=Box(200,150,12,80)
        assert flow.observe(raw) is raw
    flow=StaticAnchorFlow();flow.observe(observation(1,independent=True))
    raw=observation(0)
    assert flow.observe(raw) is raw and not flow.confirmed
