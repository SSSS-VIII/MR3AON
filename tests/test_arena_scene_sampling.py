"""Presented frame quantization must not invent platform acceleration."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_support import VisualSupports
from arena_vision import Box


@pytest.mark.parametrize('slope',[-.4,0.,.4])
def test_40hz_capture_of_60hz_scroll_preserves_velocity_and_camera_frame(slope):
    state=VisualSupports();fitted=[];instant=[]
    for i in range(15):
        t=i*.025
        presented=np.floor((t+.002)*60)/60
        dx=-600*presented;camera=40*presented
        segment=dict(kind='platform',a=(100+dx,260+camera),
                     b=(620+dx,260+520*slope+camera),confidence=.9)
        out=state.observe([segment],Box(172,210,16,40),t)
        if i>=7:fitted.append(out['scene_vx']);instant.append(out['scene_vx_raw'])
    assert max(abs(v+600)for v in instant)>190
    assert max(abs(v+600)for v in fitted)<35
    assert state.camera_y==pytest.approx(camera,abs=1e-6)


def test_scene_velocity_does_not_carry_displacement_across_an_unobserved_gap():
    state=VisualSupports()
    for i in range(8):
        t=i*.025
        state.observe([dict(kind='platform',a=(100-300*t,260),b=(600-300*t,260),confidence=.9)],None,t)
    state.observe([],None,.6)
    for i in range(8):
        t=.7+i*.025
        out=state.observe([dict(kind='platform',a=(100-100*(t-.7),260),b=(600-100*(t-.7),260),confidence=.9)],None,t)
    assert out['scene_vx']==pytest.approx(-100)
