"""Control must use the operating point actually used in OBB validation."""
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_obb_detector import ObbPerception
from arena_vision import Box,Detection
from arena_policy import VisualAvoider


def test_obb_confirmed_detections_are_not_silently_filtered_by_legacy_color_threshold():
    class Detector:
        last_ms=0;confidence=.25
        def detect(self,pixels):
            return (Box(172,210,16,40),[Detection(Box(350,220,30,30),'trap',.45)],
                    [dict(kind='rope',a=(0,260),b=(640,260),confidence=.95)],[])
    actor=ObbPerception(Detector());policy=VisualAvoider();pixels=np.zeros((360,640,4),np.uint8)
    first=actor.observe(pixels,0)
    assert first['hazard_confidence']==.25
    assert policy._objects(first)==[]
    actor.observe(pixels,.025);confirmed=actor.observe(pixels,.05)
    assert len(policy._objects(confirmed))==1
    legacy=dict(confirmed);legacy.pop('hazard_confidence')
    assert policy._objects(legacy)==[]
