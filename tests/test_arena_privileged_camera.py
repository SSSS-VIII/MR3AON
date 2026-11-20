"""Native camera reference used by the original generated bullets."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel
from arena_privileged_families import camera_x_bounds
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-camera.json').read_text())

@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_source_camera_gain_and_offset_changes_enclose_native_fixed_reference(case):
    o=case['before'];dt=case['after']['state']['time']-o['state']['time'];times=np.linspace(0.,dt,round(dt*120)+1)
    before=deepcopy(o);bounds,reason=camera_x_bounds(o,times,PlayerModel(o))
    assert not reason and o==before
    actual=case['after']['camera']['position']['x'];lo,hi=bounds
    assert lo[-1]<=actual<=hi[-1]
    if case['name']=='ground_to_rope_restores_offset':
        assert o['camera']['fields']['_cameraOffset']['x']>16
        assert case['after']['camera']['fields']['_cameraOffset']['x']==8
    if case['name']=='carrier_ground_offset_persists':
        assert case['after']['camera']['fields']['_cameraOffset']['x']>16

@pytest.mark.parametrize('name',['<StopFollowNinja>k__BackingField','_gameEndSlowDown','_cameraShift','_cameraRotate','_focusing','_ctrlAnimEnable'])
def test_special_camera_controls_do_not_fall_back_to_constant_speed(name):
    o=deepcopy(DATA['cases'][0]['before']);o['camera']['fields'][name]=True
    bounds,reason=camera_x_bounds(o,np.array([0.,.5]),PlayerModel(o))
    assert bounds is None and reason=='camera_x_unverified_control_branch'


def test_camera_source_clock_must_belong_to_observed_physics_epoch():
    o=deepcopy(DATA['cases'][0]['before']);o['camera']['fields']['_lastFixedUpdateTime']-=1
    bounds,reason=camera_x_bounds(o,np.array([0.,.5]),PlayerModel(o))
    assert bounds is None and reason=='camera_x_original_fixed_clock'
