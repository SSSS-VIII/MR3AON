"""Resolve pose points into visual instances without inventing phase evidence."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_bamboo_instances import expand_bamboo_instances,pose_phase_agreement
from arena_vision import Box


def cue(phase='locked',y=200.):
    return dict(box=Box(284,y-16,32,32),phase=phase,obb_phase=phase,
                phase_scores={phase:.99},confidence=.95,motion_kind='bamboo')


def prediction(phase='locked',y=200.,confidence=.96):
    return dict(box=[284.,184.,316.,216.],phase=phase,confidence=confidence,
                point=[300.,y,.99])


def test_two_heads_can_separately_confirm_aim_and_lock_inside_one_uncertain_crop():
    original=dict(cue('aim'),phase='uncertain',phase_scores={'aim':.01,'locked':.99})
    before=deepcopy(original)
    result=expand_bamboo_instances([original],[[prediction('aim',202.),prediction('locked',198.)]])
    assert original==before
    assert {r['phase'] for r in result}=={'aim','locked'}
    assert all(pose_phase_agreement(r) for r in result)
    assert {r['phase']:r['center_refinement']['evidence']['supporting_heads']for r in result}=={
        'aim':['obb'],'locked':['local_phase']}


def test_same_phase_six_pixel_neighbors_keep_two_clocks_instead_of_one_ring_box():
    from arena_bamboo_motion import BambooClocks
    instances=expand_bamboo_instances([cue()],[[prediction(y=197.),prediction(y=203.)]])
    assert len(instances)==2
    clocks=BambooClocks();clocks.point_uncertainty=True
    for stamp in(0.,.03,.06,.09):clocks.observe(instances,stamp)
    forecasts=clocks.forecasts(.09,-700.)
    assert len(forecasts)==2 and len({f.id for f in forecasts})==2
    assert sorted(f.box.center[1]for f in forecasts)==pytest.approx([197.,203.])


@pytest.mark.parametrize('valid',[True,False])
def test_only_valid_two_head_instance_can_confirm_the_first_lock_exposure(valid):
    from arena_bamboo_motion import BambooClocks
    clocks=BambooClocks();clocks.point_uncertainty=True
    for stamp in(0.,.03):
        clocks.observe(expand_bamboo_instances([cue('aim')],[[prediction('aim')]]),stamp)
    locked=expand_bamboo_instances([cue()],[[prediction()]])
    if not valid:locked[0]['center_refinement']['evidence']['source']='fabricated'
    clocks.observe(locked,.06)
    assert bool(clocks.forecasts(.06,-700.)) is valid


def test_same_point_from_overlapping_rois_is_not_a_second_physical_marker():
    a=prediction(confidence=.91);b=prediction(y=200.5,confidence=.98)
    result=expand_bamboo_instances([cue(),cue()],[[a],[b]])
    assert len(result)==1 and result[0]['box'].center==(300.,200.5)
    assert result[0]['confidence']==.98


@pytest.mark.parametrize('change', ['unsupported_phase','weak','invisible','nan','outside_roi',
                                  'outside_screen','no_box_overlap','inverted_box','outside_own_box'])
def test_unconfirmed_or_invalid_point_keeps_original_cue(change):
    original=cue('aim');p=prediction('aim')
    if change=='unsupported_phase':p['phase']='locked'
    elif change=='weak':p['confidence']=.79
    elif change=='invisible':p['point'][2]=.79
    elif change=='nan':p['point'][0]=float('nan')
    elif change=='outside_roi':p['point'][1]=240.
    elif change=='outside_screen':p['point'][1]=54.
    elif change=='no_box_overlap':p['box']=[350.,184.,382.,216.]
    elif change=='inverted_box':p['box']=[316.,184.,284.,216.]
    elif change=='outside_own_box':p['point'][1]=182.
    assert expand_bamboo_instances([original],[[p]])==[original]


def test_a_point_at_the_hud_edge_is_not_clipped_and_recentred_a_second_time():
    from arena_bamboo_motion import BambooClocks
    original=cue(y=63.);original['box']=Box(284,55,32,16)
    p=prediction(y=55.);p['box']=[284.,39.,316.,71.]
    instance,=expand_bamboo_instances([original],[[p]])
    assert instance['box'].center==(300.,55.)
    clocks=BambooClocks();clocks.point_uncertainty=True
    for stamp in(0.,.03,.06):clocks.observe([instance],stamp)
    forecast,=clocks.forecasts(.06,-700.)
    assert forecast.box.center[1]==55.


def test_missing_prediction_groups_cannot_silently_drop_a_cue():
    with pytest.raises(ValueError):expand_bamboo_instances([cue()],[])


@pytest.mark.parametrize('change', ['missing','phase','pose','visibility','source','heads'])
def test_an_instance_flag_alone_is_not_two_head_phase_confirmation(change):
    instance,=expand_bamboo_instances([cue()],[[prediction()]])
    field=instance['center_refinement'];evidence=field['evidence']
    if change=='missing':field['evidence']={}
    elif change=='phase':evidence['phase']='aim'
    elif change=='pose':evidence['pose']=True
    elif change=='visibility':evidence['visibility']=.79
    elif change=='source':evidence['source']='unknown'
    elif change=='heads':evidence['supporting_heads']=[]
    assert not pose_phase_agreement(instance)


def test_instance_adapter_reuses_one_pose_batch_and_preserves_other_cue_identity():
    import numpy as np
    from arena_bamboo_point import BambooPointRefiner
    class Tensor:
        def __init__(self,v):self.value=np.asarray(v)
        def cpu(self):return self
        def numpy(self):return self.value
    calls=[]
    class Model:
        names={0:'aim',1:'locked'}
        def predict(self,images,**options):
            calls.append(len(images))
            return [SimpleNamespace(boxes=SimpleNamespace(
                xyxy=Tensor([[15.5,15.5,47.5,47.5]]*2),cls=Tensor([1,1]),conf=Tensor([.96,.96])),
                keypoints=SimpleNamespace(data=Tensor([[[31.5,28.5,.99]],[[31.5,34.5,.99]]])))for _ in images]
    refiner=BambooPointRefiner.__new__(BambooPointRefiner)
    refiner.model=Model();refiner.options={};refiner.instances=True
    refiner.dummy=np.zeros((64,64,3),np.uint8)
    other=dict(motion_kind=None,phase='none',box=Box(400,100,10,10))
    result=refiner.refine(np.zeros((360,640,3),np.uint8),[cue(),other])
    assert calls==[1]and result[0]is other
    assert len(result)==3 and refiner.last_stats['pose_instances']==2
    assert sorted(c['box'].center[1]for c in result[1:])==pytest.approx([197.,203.])
