"""Local same-model recovery preserves screen coordinates and role-only input."""
from types import SimpleNamespace
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_obb_detector import ObbDetector,ObbPerception,player_recovery_window
from arena_vision import Box


class Tensor:
    def __init__(self,value):self.value=np.asarray(value)
    def cpu(self):return self
    def numpy(self):return self.value


def detector(cls=0):
    d=ObbDetector.__new__(ObbDetector)
    d.player_box=Box(188,210,16,40);d.player_x=196.;d.options=dict(imgsz=640,conf=.25)
    d.profile=dict(classes=[dict(kind='player'),dict(kind='hazard',shape='BoxCollider',motion_kind='trap')])
    class Model:
        def predict(self,crop,**options):
            assert crop.shape==(240,240,3)and options['imgsz']==320
            obb=SimpleNamespace(cls=Tensor([cls]),conf=Tensor([.45]),
                xyxyxyxy=Tensor([[[112,100],[128,100],[128,140],[112,140]]]))
            return [SimpleNamespace(obb=obb)]
    d.model=Model()
    return d


def test_local_player_coordinates_return_to_the_original_full_screen_plane():
    d=detector()
    assert d.recover_player(np.zeros((360,640,3),np.uint8))==Box(188,210,16,40)
    assert d.options['imgsz']==640


def test_hazards_from_the_extra_crop_cannot_become_role_or_duplicate_hazards():
    assert detector(cls=1).recover_player(np.zeros((360,640,3),np.uint8))is None


def test_no_previous_role_cannot_seed_a_local_false_identity():
    d=detector();d.player_box=None;d.model=None
    assert d.recover_player(np.zeros((360,640,3),np.uint8))is None


def test_motion_sweep_changes_search_only_and_preserves_last_actual_role():
    d=detector();actual=d.player_box
    d.player_roi_hint=Box(188,90,16,40)
    found=d.recover_player(np.zeros((360,640,3),np.uint8))
    assert d.last_player_roi_window==(76,50,240,240)
    assert d.last_player_roi_hint_used is True
    assert found==Box(188,150,16,40)
    assert d.player_box is actual


@pytest.mark.parametrize('hint', [Box(188,float('nan'),16,40),Box(188,90,0,40),
                                Box(600,90,16,40),Box(188,-200,16,40),object()])
def test_bad_or_uncoverable_hint_keeps_original_search(hint):
    d=detector();d.player_roi_hint=hint
    assert d.recover_player(np.zeros((360,640,3),np.uint8))==Box(188,210,16,40)
    assert d.last_player_roi_hint_used is False


def test_even_a_valid_hint_cannot_invent_the_first_role_identity():
    d=detector();d.player_box=None;d.player_roi_hint=Box(188,90,16,40);d.model=None
    assert d.recover_player(np.zeros((360,640,3),np.uint8))is None


def test_swept_window_respects_real_image_boundaries():
    assert player_recovery_window(Box(0,0,20,40),(360,640,3),Box(20,80,20,40))==(0,0,240,240)
    assert player_recovery_window(Box(610,310,20,40),(360,640,3),Box(600,300,20,40))==(400,120,240,240)


def perception_for_query():
    p=ObbPerception.__new__(ObbPerception)
    p.detector=SimpleNamespace(player_roi_hint=Box(0,0,2,2))
    p.predictive_player_roi=True;p.last_seen_player=.7
    context=dict(time=1.,player=Box(188,90,16,40),phase='jump1_rising',jumps=1,
                 motion=dict(name='jump1',started=.8),rope=None)
    p.last_observation=dict(time=.7,player=None,phase='unknown')
    p.input_timeline=SimpleNamespace(prepared_stamp=1.,missing_role_context=lambda:(context,None))
    return p,context


def test_timeline_motion_guides_crop_without_promoting_predicted_body_to_pixels():
    p,context=perception_for_query();before=dict(p.last_observation)
    p.prepare_player_roi(1.)
    assert p.detector.player_roi_hint.center==context['player'].center
    assert p.last_observation==before and p.last_seen_player==.7


@pytest.mark.parametrize('condition', ['disabled','unprepared','missing_context','not_jump','expired'])
def test_query_requires_current_own_jump_and_clears_stale_hints(condition):
    p,context=perception_for_query()
    if condition=='disabled':p.predictive_player_roi=False
    elif condition=='unprepared':p.input_timeline.prepared_stamp=None
    elif condition=='missing_context':p.input_timeline.missing_role_context=lambda:(None,'no_pixels')
    elif condition=='not_jump':context['motion']['name']='rope_down'
    elif condition=='expired':context['motion']['started']=-10.
    p.prepare_player_roi(1.)
    assert p.detector.player_roi_hint is None
