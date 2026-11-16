"""Reviewed native support-type corrections and optional detector integration."""
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import sys,json
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_support_refiner import SupportTypeRefiner,crop_center
from arena_obb_detector import ObbDetector

DATA=json.loads((Path(__file__).parent/'fixtures/arena-support-type-votes.json').read_text())


class Array:
    def __init__(self,value):self.value=np.asarray(value)
    def cpu(self):return self
    def numpy(self):return self.value


class Classifier:
    def __init__(self,probabilities):self.probabilities=probabilities;self.calls=0
    def predict(self,crops,**kwargs):
        self.calls+=1
        assert all(c.shape==(128,128,3)for c in crops)
        return [SimpleNamespace(probs=SimpleNamespace(data=Array(self.probabilities)))for _ in crops]


def refiner(probabilities):
    r=SupportTypeRefiner.__new__(SupportTypeRefiner);r.model=Classifier(probabilities);r.options={}
    r.last_ms=0.;r.last_votes=[]
    return r


@pytest.mark.parametrize('case',DATA['cases'][:2],ids=lambda c:c['segment']['kind']+'-'+c['expected_kind'])
def test_real_pixel_votes_correct_original_type_without_changing_geometry(case):
    r=refiner(case['probabilities']);segment=deepcopy(case['segment']);original=deepcopy(segment)
    result=r.refine(np.zeros((360,640,3),np.uint8),[segment])[0]
    assert result['kind']==case['expected_kind']and result['raw_kind']==segment['kind']
    assert result['a']==segment['a']and result['b']==segment['b']
    assert result['confidence']==segment['confidence']
    assert segment==original and r.last_votes[0]['changed']


def test_existing_ground_is_preserved_even_when_classifier_would_retype_it():
    case=DATA['cases'][2];r=refiner(case['probabilities']);segment=deepcopy(case['segment'])
    assert r.refine(np.zeros((360,640,3),np.uint8),[segment])==[segment]
    assert r.model.calls==0 and not r.last_votes


@pytest.mark.parametrize('probabilities',[[.49,.51,0.],[float('nan'),1.,0.],[0.,1.1,-.1]])
def test_uncertain_or_invalid_type_vote_keeps_original_support(probabilities):
    r=refiner(probabilities);segment=deepcopy(DATA['cases'][0]['segment'])
    assert r.refine(np.zeros((360,640,3),np.uint8),[segment])==[segment]


def test_unvalidated_clipped_left_and_tiny_or_nonfinite_segments_do_not_call_model():
    r=refiner([0.,1.,0.]);segments=[dict(kind='rope',a=(0,260),b=(640,260)),
        dict(kind='rope',a=(100,260),b=(110,260)),dict(kind='rope',a=(100,float('nan')),b=(500,260))]
    assert r.refine(np.zeros((360,640,3),np.uint8),segments)is segments
    assert r.model.calls==0 and r.last_ms==0.


def test_detector_calls_optional_classifier_on_pixels_before_support_tracking():
    detector=ObbDetector.__new__(ObbDetector)
    detector.profile={'classes':[dict(name='role',kind='player'),dict(name='float',kind='floating_platform',shape='segment')]}
    detector.player_x=180.;detector.player_box=None;detector.options={};detector.phase_refiner=None
    detector.support_refiner=refiner([0.,1.,0.])
    quads=[[[172,200],[188,200],[188,238],[172,238]],[[300,200],[500,200],[500,204],[300,204]]]
    obb=SimpleNamespace(xyxyxyxy=Array(quads),cls=Array([0,1]),conf=Array([.9,.8]))
    detector.model=SimpleNamespace(predict=lambda *a,**k:[SimpleNamespace(obb=obb)])
    rgb=np.zeros((360,640,3),np.uint8)
    player,_,supports,_=detector.detect(rgb)
    assert player is not None and supports[0]['kind']=='platform'
    assert supports[0]['raw_kind']=='floating_platform'and supports[0]['confidence']==.8
    detector.support_refiner=None
    assert detector.detect(rgb)[2][0]['kind']=='floating_platform'


def test_none_class_abstains_without_deleting_or_retyping_the_original_line():
    r=refiner([0.,1.,0.,0.]);r.names=('floating_platform','none','platform','rope')
    segment=deepcopy(DATA['cases'][0]['segment'])
    assert r.refine(np.zeros((360,640,3),np.uint8),[segment])==[segment]
    assert r.last_votes[0]['kind']=='none'and not r.last_votes[0]['changed']
