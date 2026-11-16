"""Separately verify observed rebound correction and a native-legal key gap."""
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
import json
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Track
from arena_mpc import MpcAvoider
from arena_pinball_impulse import refresh_fast_rebound
from arena_projection import SCALE

DATA=json.loads((Path(__file__).parent/'fixtures/arena-early-down-rebound.json').read_text())


def state(bootstrap):
    row=DATA['input'];obs=deepcopy(row);obs['player']=Box(**obs['player']);obs['tracks']=[]
    for t in row['tracks']:
        kw={k:deepcopy(v)for k,v in t.items()if k in{f.name for f in fields(Track)}}
        kw['box']=Box(**kw['box']);track=Track(**kw)
        if bootstrap and track.kind=='pinball':
            box=track.box;x,y=track.history[-1][1:];track.pinball_fast_rebound=True
            track.box=Box(x+track.reference[0]-box.w/2,y+track.reference[1]-box.h/2,box.w,box.h)
            if refresh_fast_rebound(track,SCALE):track=track.at(row['time']-DATA['source_image_time'])
            else:track.box=box
        obs['tracks'].append(track)
    return obs


@pytest.mark.parametrize('bootstrap,gap,expected',[
    (False,.1,(None,'mpc_wait')),(False,.04,(None,'mpc_wait')),
    (True,.1,(None,'mpc_wait')),(True,.04,('down','mpc_air_down')),
])
def test_real_failed_state_needs_both_correct_motion_and_an_available_legal_action(bootstrap,gap,expected):
    # Match the native runner: recovery cost is a class method.
    planner=type('ConfiguredPolicy',(MpcAvoider,),dict(ground_static_search=True,
        ground_reserve_recovery=True,ordinary_air_down_gap=gap))()
    planner.last_action=DATA['previous_action_time']
    obs=state(bootstrap)
    assert 'jump2'not in planner._options(obs,obs['time'])
    assert ('air_down'in planner._options(obs,obs['time']))==(gap==.04)
    assert planner.choose(obs)==expected


def test_original_ui_accepts_down_after_one_to_four_jump_ticks_without_changing_hp():
    for case in DATA['native_calibration_expected_only']:
        assert case['fixed_dt']==pytest.approx(.02)
        assert case['before_physics']=='jump: 14'
        assert case['down_physics'][0]=='rollToLineDown: 3'
        assert case['final_physics']=='runOnLineDown: 2'and case['health']==5000


@pytest.mark.parametrize('phase,name',[('flip_up','rope_up'),('flip_down','air_down')])
def test_shorter_ordinary_down_gap_does_not_relax_unprobed_reverse_inputs(phase,name):
    planner=MpcAvoider();planner.ordinary_air_down_gap=.04
    segment=dict(id=1,kind='rope',a=(0.,260.),b=(640.,260.),vx=0.,vy=0.)
    obs=dict(time=1.06,phase=phase,motion=dict(name=name,started=1.,destination='rope'),
             player=Box(176.,246.,8.,8.),jumps=2,rope=260.,terrain=None,
             rope_segment=segment,rope_segments=[segment],last_input_time=1.)
    wanted='air_down'if phase=='flip_up'else'air_up'
    assert wanted not in planner._options(obs,obs['time'])
    assert wanted in planner._options(dict(obs,time=1.11),1.11)
    assert MpcAvoider().ordinary_air_down_gap==.1
