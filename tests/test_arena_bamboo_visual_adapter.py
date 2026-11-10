"""New standard YOLO classes enter the existing pixels-only actor safely."""
import json
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_obb_detector import decode,ObbPerception
from arena_vision import Box,Detection,Tracker,serializable
from arena_projection import SCALE
from arena_policy import VisualAvoider


PROFILE=dict(classes=[dict(kind='cue',shape='cue',motion_kind='bamboo',phase='locked'),
                      dict(kind='hazard',shape='BoxCollider',motion_kind='bamboo',phase='attack')])


def test_reticle_is_a_phase_cue_and_clipped_projectile_recovers_original_length():
    marker=[[290,190],[310,190],[310,210],[290,210]]
    clipped=[[600,190],[640,190],[640,198],[600,198]]
    _,hazards,_,cues=decode([marker,clipped],[0,1],[.9,.9],PROFILE)
    assert cues[0]['phase']=='locked'and cues[0]['motion_kind']=='bamboo'
    assert len(hazards)==1 and hazards[0].active and hazards[0].kind=='bamboo'
    assert hazards[0].box.w==pytest.approx(3*SCALE)
    assert max(q[0]for q in hazards[0].quad)>640


def test_source_speed_prior_keeps_a_fast_projectile_associated_from_its_first_frame():
    tracker=Tracker(adaptive=True)
    for t,x in[(0.,600.),(.025,522.5),(.05,445.)]:
        detected=Detection(Box(x,180,118,8),'bamboo',.9,True,False,'attack',
                           collider_shape='BoxCollider',velocity_prior=(-3100.,0.))
        tracks=tracker.update([detected],t,(0,0))
    assert len(tracks)==1 and tracks[0].observations==3
    assert tracks[0].vx==pytest.approx(-3100.)
    assert VisualAvoider()._hazard(tracks[0],.1).x==pytest.approx(135.)


def test_visual_observer_emits_a_timed_forecast_without_native_state():
    class Detector:
        profile=PROFILE
        last_ms=0.
        confidence=.25
        def detect(self,rgb):
            return Box(172,211,16,37),[],[dict(kind='rope',a=(0,260),b=(640,260),confidence=.9)],self.cues
    detector=Detector();actor=ObbPerception(detector);rgb=np.zeros((360,640,3),np.uint8)
    for t,phase in[(0.,'aim'),(.03,'aim'),(.06,'locked'),(.09,'locked')]:
        detector.cues=[dict(box=Box(292,192,16,16),confidence=.9,motion_kind='bamboo',phase=phase)]
        obs=actor.observe(rgb,t)
    forecast,=obs['tracks']
    assert forecast.kind=='bamboo_forecast'and forecast.future(.1).x>600
    assert forecast in VisualAvoider()._objects(obs)
    json.dumps(serializable(obs))
