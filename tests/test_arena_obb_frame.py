"""Original-image geometry and explicit OBB preprocessing, without GPU use."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_obb_detector as obb
from arena_vision import Box


@pytest.mark.parametrize('quad,expected',[
    ([[650,100],[700,100],[700,200],[650,200]],False),
    ([[620,400],[680,340],[740,400],[680,460]],False), # overlapping AABB, separated OBB
    ([[580,400],[640,340],[700,400],[640,460]],True),
    ([[-30,150],[10,150],[10,190],[-30,190]],True),
    ([[-30,150],[-1,150],[-1,190],[-30,190]],False),
    ([[-1e12,-1e12],[1e12,-1e12],[1e12,1e12],[-1e12,1e12]],True),
    ([[1000,-1e12],[1e12,-1e12],[1e12,1e12],[1000,1e12]],False),
    ([[640,100],[660,100],[660,200],[640,200]],True), # line contact
    ([[610,390],[670,330],[730,390],[670,450]],True), # point contact at (640,360)
    ([[-10,150],[650,150],[650,190],[-10,190]],True), # no vertex in frame
    ([[200,360],[240,360],[240,380],[200,380]],True),
])
def test_closed_rotated_quad_frame_intersection(quad,expected):
    assert obb.quad_intersects_frame(quad)is expected


def test_nonfinite_and_invalid_quad_are_not_visible():
    assert not obb.quad_intersects_frame([[0,0],[1,0],[1,float('nan')],[0,1]])
    assert not obb.quad_intersects_frame([[0,0],[1,0]])


@pytest.mark.parametrize('kind',['player','hazard','slice_target','cue','rope','platform','floating_platform'])
def test_every_kind_rejects_only_wholly_outside_geometry(kind):
    profile=dict(classes=[dict(kind=kind,shape='BoxCollider',motion_kind='trap')])
    outside=[[200,400],[280,400],[280,440],[200,440]]
    partial=[[200,350],[280,350],[280,390],[200,390]]
    assert obb.decode([outside],[0],[.9],profile)==(None,[],[],[])
    player,hazards,supports,cues=obb.decode([partial],[0],[.9],profile)
    if kind=='player':assert player==Box(200,350,80,40)
    elif kind in('hazard','slice_target'):assert hazards[0].quad==tuple(map(tuple,partial))
    elif kind=='cue':assert cues[0]['box']==Box(200,350,80,40)
    else:assert supports[0]['a']==(200.,370.)and supports[0]['b']==(280.,370.)


def test_guard_uses_physical_arrow_width_not_the_wider_training_band():
    profile=dict(classes=[dict(kind='hazard',shape='BoxCollider',motion_kind='arrow',
                               inference_short_side_world=.07)])
    band=[[180,354],[280,354],[280,374],[180,374]]
    assert obb.quad_intersects_frame(band)
    assert obb.decode([band],[0],[.9],profile)==(None,[],[],[])


def test_existing_hud_policy_still_applies_after_geometry_check():
    profile=dict(classes=[dict(kind='hazard',shape='BoxCollider',motion_kind='trap')])
    top=[[200,44],[240,44],[240,64],[200,64]]
    side=[[80,350],[120,350],[120,380],[80,380]]
    assert obb.quad_intersects_frame(top)and obb.quad_intersects_frame(side)
    assert obb.decode([top,side],[0,0],[.9,.9],profile)==(None,[],[],[])


def test_explicit_original_image_size_and_large_enclosure():
    profile=dict(classes=[dict(kind='hazard',shape='BoxCollider',motion_kind='trap')])
    outside=[[410,150],[430,150],[430,190],[410,190]]
    assert len(obb.decode([outside],[0],[.9],profile)[1])==1
    assert obb.decode([outside],[0],[.9],profile,image_shape=(360,400))==(None,[],[],[])
    enclosure=[[-1000,-1000],[1640,-1000],[1640,1360],[-1000,1360]]
    assert obb.decode([enclosure],[0],[.9],profile)[1][0].quad==tuple(map(tuple,enclosure))


def checkpoint(tmp_path):
    folder=tmp_path/'fit';(folder/'weights').mkdir(parents=True)
    weights=folder/'weights/model.pt';weights.write_bytes(b'cpu stub')
    profile=dict(task='obb',geometry='gameplay_plane',classes=[dict(kind='player',name='player')])
    (folder/'profile.json').write_text(json.dumps(profile))
    return weights


@pytest.mark.parametrize('rect',[None,False,True])
def test_square_requires_explicit_constructor_option(monkeypatch,tmp_path,rect):
    calls=[]
    model=SimpleNamespace(task='obb',names={0:'player'},predict=lambda pixels,**options:calls.append(options))
    monkeypatch.setattr(obb,'offline_sdk',lambda:SimpleNamespace(YOLO=lambda path:model))
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(set_num_threads=lambda _:None))
    detector=obb.ObbDetector(checkpoint(tmp_path),rect=rect)
    assert len(calls)==9
    if rect is None:assert all('rect'not in call for call in calls)and'rect'not in detector.options
    else:assert all(call['rect']is rect for call in calls)


def test_invalid_rect_is_rejected_before_model_loading():
    with pytest.raises(ValueError,match='rect'):
        obb.ObbDetector('unused',rect='false')


def test_factory_forwards_only_explicit_obb_rect(monkeypatch,tmp_path):
    import arena_yolo_detector as factory
    monkeypatch.setattr(obb,'ObbDetector',lambda weights,**options:options)
    monkeypatch.setattr(obb,'ObbPerception',lambda detector:detector)
    weights=checkpoint(tmp_path)
    assert factory.make_perception(weights)==dict(phase_refiner=None)
    assert factory.make_perception(weights,obb_rect=False)==dict(phase_refiner=None,rect=False)


def test_role_roi_rejects_padding_before_translation_and_keeps_partial_role():
    class Values:
        def __init__(self,values):self.values=np.asarray(values)
        def cpu(self):return self
        def numpy(self):return self.values
    outside=[[112,-30],[128,-30],[128,-10],[112,-10]]
    partial=[[112,-10],[128,-10],[128,10],[112,10]]
    prediction=SimpleNamespace(cls=Values([0,0]),conf=Values([.99,.8]),xyxyxyxy=Values([outside,partial]))
    detector=object.__new__(obb.ObbDetector)
    detector.profile=dict(classes=[dict(kind='player')]);detector.player_box=Box(172,210,16,40)
    detector.player_x=180.;detector.options={}
    detector.model=SimpleNamespace(predict=lambda *a,**k:[SimpleNamespace(obb=prediction)])
    assert detector.recover_player(np.zeros((360,640,3),np.uint8))==Box(172,100,16,20)
