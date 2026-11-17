"""Original float down is a down-pass, not the solid-ground slide prior."""
from dataclasses import fields
from copy import deepcopy
import json
from pathlib import Path
import pytest
from arena_vision import Box,Track
from arena_policy import ground_slide_supported
from arena_mpc import MpcAvoider

FIXTURES=Path(__file__).parent/'fixtures'


def terrain(kind='platform',**extra):
    return dict(source='neural_segments',selected_id=7,segments=[dict(id=7,kind=kind,**extra)])


def test_original_down_pass_keeps_normal_body_and_next_key_is_jump2():
    rows=json.loads((FIXTURES/'arena-floating-down-native.json').read_text())['rows']
    plain=next(r for r in rows if r['action']=='none');down=next(r for r in rows if r['action']=='down')
    assert plain['damage']==down['damage']==0
    assert plain['fall_physics']=='fallFromRun: 13'and 'jump: 14'in plain['jump_physics']
    assert down['fall_physics']=='fall: 15'and 'jump2: 16'in down['jump_physics']
    assert down['before_air']['left']<down['fall_position']['x']<down['before_air']['right']
    moving=[r for r in down['down_samples']if r['t']>.02]
    assert all(r['physics']=='fall: 15'for r in moving)
    assert all(r['w']==pytest.approx(.4,abs=.001)and r['h']==pytest.approx(.936,abs=.001)for r in moving)
    assert moving[-1]['y']<moving[0]['y']-1


def test_modeled_slide_requires_solid_visual_support():
    assert ground_slide_supported(dict(terrain=terrain()))
    assert not ground_slide_supported(dict(terrain=terrain('floating_platform')))
    assert not ground_slide_supported(dict(terrain=terrain(raw_kind='floating_platform')))
    assert not ground_slide_supported(dict(terrain=terrain('rope')))
    assert not ground_slide_supported(dict(terrain=dict(source='neural_segments',selected_id=8,segments=[])))


def test_mpc_option_gate_preserves_ground_jump_and_legacy_mode():
    state=dict(time=2.,phase='ground',jumps=0,terrain=terrain('floating_platform'),player=Box(170,200,16,38),rope=None)
    old=MpcAvoider();new=MpcAvoider();new.solid_ground_slide_only=True
    assert old._options(state,2.)==[None,'jump1','slide']
    assert new._options(state,2.)==[None,'jump1']
    assert new._options(dict(state,terrain=terrain()),2.)==old._options(state,2.)


def test_actual_float_frame_reproduces_old_slide_and_candidate_excludes_it():
    fixture=json.loads((FIXTURES/'arena-floating-down-action.json').read_text());obs=deepcopy(fixture['observation'])
    obs['player']=Box(**obs['player']);known={f.name for f in fields(Track)}
    assert not any(t.get('resource')=='source_poleaxe_forecast'for t in obs['tracks'])
    obs['tracks']=[Track(**{k:(Box(**v)if k=='box'else v)for k,v in t.items()if k in known})for t in obs['tracks']]
    old=MpcAvoider();new=MpcAvoider();new.solid_ground_slide_only=True
    assert list(old.choose(deepcopy(obs)))==fixture['expected_original']
    choice=new.choose(deepcopy(obs))
    assert choice[0]!='slide'and 'slide'not in choice[1]
    assert fixture['observation']['terrain']==obs['terrain']
