"""Local same-model recovery preserves screen coordinates and role-only input."""
from types import SimpleNamespace
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_obb_detector import ObbDetector
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
