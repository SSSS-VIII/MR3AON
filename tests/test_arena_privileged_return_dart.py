"""Original return-dart transitions, including its forward tracking interval."""
import copy
import json
from pathlib import Path
import sys
import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from dataclasses import replace

CASES=json.loads((Path(__file__).parent/'fixtures/arena-privileged-return-dart.json').read_text())['cases']


@pytest.mark.parametrize('case',CASES,ids=lambda c:str(c['phase']))
def test_half_second_native_phase_transition_and_sphere_match(case):
    before,after=case['before'],case['after']
    assert before['state']['health']==after['state']['health']
    times=np.linspace(0,case['seconds'],61)
    hazards,missing=hazard_forecasts(before,times,PlayerModel(before))
    assert not missing and len(hazards)==1
    c=after['enemies'][0]['colliders'][0]
    center=np.array([c['center'][a]for a in ('x','y')])
    extent=np.array([c['extents'][a]for a in ('x','y')])
    assert np.linalg.norm(hazards[0].centers[-1]-center)<.001
    assert np.linalg.norm(hazards[0].extents[-1]-extent)<1e-5
    assert hazards[0].geometry=='sphere'


def test_visual_rotation_cannot_be_applied_to_an_unvalidated_box_variant():
    before=copy.deepcopy(CASES[0]['before'])
    before['enemies'][0]['colliders'][0]['type']='BoxCollider'
    hazards,missing=hazard_forecasts(before,np.linspace(0,.5,61),PlayerModel(before))
    assert not hazards
    assert missing[0]['reason']=='return_dart_requires_original_centered_sphere'


def test_future_player_speed_changes_cannot_keep_a_constant_velocity_stop_threshold():
    before=CASES[0]['before'];player=PlayerModel(before);times=np.linspace(0,.5,61)
    states=[replace(player.initial,vx=player.speed*1.5)for _ in times]
    hazards,missing=hazard_forecasts(before,times,player,states)
    assert not hazards
    assert missing[0]['reason']=='return_dart_native_player_speed_transition'
