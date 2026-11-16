"""Measured scene flow disambiguates newly seen repeated traps."""
from pathlib import Path
import sys
import math
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Detection,Tracker


def traps(centers,flow=None,y=200.,kind='trap'):
    return [Detection(Box(x-8,y-40,16,80),kind,.95,
                      collider_shape='BoxCollider',scene_velocity_x=flow)for x in centers]


@pytest.mark.parametrize('times',[(0.,.06,.12),(0.,.04,.11),(0.,.025,.075)])
def test_repeated_traps_keep_identity_instead_of_swapping_to_the_next_blade(times):
    tracker=Tracker(adaptive=True);initial=[400.,460.,520.];identities=None
    for index,stamp in enumerate(times):
        camera=8.*index;positions=[x-1000*stamp for x in initial]
        tracks=tracker.update(traps(positions,-1000.,200.+camera),stamp,(0.,camera))
        seen=sorted((t for t in tracks if t.seen==stamp),key=lambda t:t.box.center[0])
        if identities is None:identities=[t.id for t in seen]
        assert [t.id for t in seen]==identities
    assert len(tracker.tracks)==3
    assert all(t.observations==3 and t.vx==pytest.approx(-1000.)for t in tracker.tracks)
    assert all(t.vy==pytest.approx(0.)for t in tracker.tracks)


def test_scene_prior_does_not_replace_a_mature_objects_own_motion():
    tracker=Tracker(adaptive=True)
    for stamp in (0.,.04,.08,.12):
        tracks=tracker.update(traps([400.+200*stamp],-500.),stamp,(0.,0.))
    assert len(tracks)==1 and tracks[0].observations==4
    assert tracks[0].vx==pytest.approx(200.)
    assert tracks[0].future(.2).center[0]==pytest.approx(464.)


@pytest.mark.parametrize('flow',(None,float('nan'),float('inf')))
def test_unknown_scene_motion_keeps_the_previous_matching_path(flow):
    tracker=Tracker(adaptive=True)
    first=tracker.update(traps([400.],flow),0.,(0.,0.))[0].id
    for stamp in (.04,.08):
        tracks=tracker.update(traps([400.-200*stamp],flow),stamp,(0.,0.))
    assert len(tracks)==1 and tracks[0].id==first
    assert math.isfinite(tracks[0].vx)and tracks[0].vx==pytest.approx(-200.)


def test_obb_adapter_supplies_only_observed_scene_flow_to_new_trap_matching():
    import numpy as np
    from arena_obb_detector import ObbPerception
    class Detector:
        last_ms=1.
        tick=0
        def detect(self,rgb):
            stamp=self.tick*.06;self.tick+=1
            self.detections=(traps([400.-1000*(stamp-.12),460.-1000*(stamp-.12),520.-1000*(stamp-.12)])
                             if self.tick>=3 else [])
            self.detections.append(Detection(Box(580,100,20,20),'eye_enemy',.95))
            return Box(172,210,16,40),self.detections,[dict(kind='platform',
                a=(0,260),b=(620-1000*stamp,260),confidence=.99)],[]
    detector=Detector();actor=ObbPerception(detector)
    image=np.zeros((360,640,4),np.uint8)
    first=actor.observe(image,0.)
    assert not first['scene_motion_observed']
    assert all(d.scene_velocity_x is None for d in detector.detections)
    for index in (1,2,3,4):obs=actor.observe(image,index*.06)
    assert obs['scene_motion_observed']and obs['scene_velocity_x']==pytest.approx(-1000.)
    assert all(d.scene_velocity_x==pytest.approx(-1000.)for d in detector.detections if d.kind=='trap')
    assert detector.detections[-1].scene_velocity_x is None
    mature=[t for t in obs['tracks']if t.kind=='trap']
    assert len(mature)==3 and all(t.observations==3 and t.vx==pytest.approx(-1000.)for t in mature)
