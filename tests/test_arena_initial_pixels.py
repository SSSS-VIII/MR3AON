"""A native black entrance can wait; gameplay never rearms that exception."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from arena_visual_runner import InitialPixels


def test_opaque_black_intro_waits_once_and_does_not_mask_a_later_frozen_screen():
    image=np.zeros((10,10,4),np.uint8);image[:,:,3]=255
    gate=InitialPixels()
    assert gate.check(image,0)=='waiting'
    assert gate.check(image,.3)=='waiting'
    image[5,5,0]=1
    assert gate.check(image,.4)=='ready'
    image[5,5,0]=0
    assert gate.check(image,10)=='ready'
    assert gate.first_visible_elapsed==.4 and gate.black_frames==2


def test_a_never_visible_entrance_has_a_bounded_timeout():
    gate=InitialPixels();image=np.zeros((10,10,4),np.uint8)
    assert gate.check(image,1.99)=='waiting'
    assert gate.check(image,2)=='timeout'
    assert gate.first_visible_elapsed is None
