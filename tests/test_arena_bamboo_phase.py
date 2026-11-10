import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_bamboo_phase import BambooPhaseRefiner,refine_cues,reticle_crop
from arena_bamboo_motion import BambooClocks
from arena_vision import Box


def cue(phase):
    return dict(box=Box(280,180,40,40),motion_kind='bamboo',phase=phase,confidence=.9)


def test_fixed_crop_preserves_ring_size_when_detector_box_shrinks():
    image=np.arange(360*640*3,dtype=np.uint8).reshape(360,640,3)
    assert np.array_equal(reticle_crop(image,Box(280,180,40,40)),
                          reticle_crop(image,Box(290,190,20,20)))
    assert reticle_crop(image,Box(-10,180,20,20)).shape==(64,64,3)


def test_disagreement_is_not_a_definite_aim_or_lock_and_preserves_geometry():
    generic=dict(box=Box(1,2,3,4),confidence=.8)
    cues=[cue('locked'),generic,cue('aim')]
    result=refine_cues(cues,[dict(aim=.97,locked=.02,none=.01),dict(aim=.01,locked=.98,none=.01)])
    assert [c.get('phase')for c in result]==['uncertain',None,'uncertain']
    assert result[0]['box']==cues[0]['box']and result[0]['confidence']==.9
    assert result[2]['obb_phase']=='aim'and result[1]is generic


def test_consensus_confirms_both_aim_and_locked():
    result,=refine_cues([cue('locked')],[dict(aim=.01,locked=.98,none=.01)])
    assert result['phase']=='locked'
    result,=refine_cues([cue('aim')],[dict(aim=.97,locked=.02,none=.01)])
    assert result['phase']=='aim'


def test_uncertainty_does_not_supply_a_new_aim_boundary_or_reset_a_lock():
    clocks=BambooClocks()
    for stamp,phase in[(0.,'aim'),(.03,'uncertain'),(.06,'locked'),(.09,'uncertain'),(.12,'locked')]:
        clocks.observe([cue(phase)],stamp)
    forecast,=clocks.forecasts(.12,-700.)
    assert forecast.fire_earliest<=1. and forecast.fire_latest==pytest.approx(1.10)
    for stamp in(.15,.18):clocks.observe([cue('uncertain')],stamp)
    after,=clocks.forecasts(.18,-700.)
    assert after.fire_latest==forecast.fire_latest


def test_ambiguous_and_background_crops_cannot_start_a_launch_clock():
    clocks=BambooClocks()
    for i in range(5):
        result=refine_cues([cue('locked'),cue('aim')],
            [dict(aim=.45,locked=.54,none=.01),dict(aim=.01,locked=.01,none=.98)])
        assert [c['phase']for c in result]==['uncertain','none']
        clocks.observe(result,i*.03)
    assert not clocks.forecasts(.12,-700.)


def test_ambiguous_transition_keeps_last_aim_as_an_onset_bound():
    clocks=BambooClocks()
    clocks.observe([cue('aim')],0.)
    for stamp in(.05,.10,.15,.20):clocks.observe([cue('uncertain')],stamp)
    for stamp in(.25,.28):clocks.observe([cue('locked')],stamp)
    forecast,=clocks.forecasts(.28,-700.)
    assert forecast.fire_earliest==pytest.approx(.94)
    assert forecast.fire_latest==pytest.approx(1.29)
    assert forecast.fire_latest-forecast.fire_earliest<.4


def test_uncertain_class_duplicate_does_not_hide_a_confirmed_lock():
    clocks=BambooClocks();clocks.observe([cue('aim')],0.)
    for stamp in(.03,.06):
        uncertain=dict(cue('uncertain'),confidence=.99)
        clocks.observe([uncertain,dict(cue('locked'),confidence=.8)],stamp)
    forecast,=clocks.forecasts(.06,-700.)
    assert forecast.fire_latest==pytest.approx(1.07)


def test_gpu_batch_padding_never_creates_additional_reticles():
    from types import SimpleNamespace
    class Tensor:
        def cpu(self):return self
        def numpy(self):return np.array([.01,.98,.01])
    class Model:
        def predict(self,crops,**options):
            self.count=len(crops)
            return [SimpleNamespace(probs=SimpleNamespace(data=Tensor()))for _ in crops]
    refiner=BambooPhaseRefiner.__new__(BambooPhaseRefiner)
    refiner.model=Model();refiner.options={};refiner.threshold=.8
    refiner.profile=dict(classes=['aim','locked','none'])
    result=refiner.refine(np.zeros((360,640,3),np.uint8),[cue('locked')for _ in range(13)])
    assert refiner.model.count==16 and len(result)==13
    assert all(c['phase']=='locked'for c in result)


def test_scenes_without_bamboo_do_not_call_the_extra_model():
    refiner=BambooPhaseRefiner.__new__(BambooPhaseRefiner);refiner.last_ms=5.
    cues=[dict(box=Box(1,2,3,4),confidence=.9)]
    assert refiner.refine(np.zeros((360,640,3),np.uint8),cues)is cues
    assert refiner.last_ms==0.
