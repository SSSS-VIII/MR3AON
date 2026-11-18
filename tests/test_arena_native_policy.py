from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab'))
from native_policy import decision


def observation(phase='runOnLine: 1'):
    return dict(state=dict(physics=phase,speed=18.5,position=dict(x=0,y=.75)),
        role=[dict(center=dict(x=0,y=.75),extents=dict(x=.18,y=.468))],jumps_used=0,
        support=dict(start=dict(x=-16,y=0),finish=dict(x=32,y=0),is_line=True,continues=True),hazards=[])


def hazard(x,y):return dict(id=1,center=dict(x=x,y=y),extents=dict(x=.2,y=.8),enabled=False)


def test_dormant_native_damage_volume_causes_action_before_contact():
    obs=observation();obs['hazards']=[hazard(9,1)]
    proposed=decision(obs)
    assert proposed['order'][0]=='down'and proposed['nearest'][0]['ttc']>.4
    assert proposed['uses_original_colliders']
    obs['hazards']=[hazard(24,1)]
    assert decision(obs)['order'][0]=='none'


def test_rope_below_does_not_flip_into_a_still_imminent_upper_hazard():
    obs=observation('runOnLineDown: 2');obs['hazards']=[hazard(9,-1)]
    assert decision(obs)['order'][0]=='jump'
    obs['hazards'].append(hazard(2,1))
    assert decision(obs)['order'][0]=='none'


def test_native_slope_height_and_real_support_continuation_affect_proposals():
    obs=observation();obs['support'].update(start=dict(x=0,y=0),finish=dict(x=12,y=3))
    obs['hazards']=[hazard(9,3.25)]
    assert decision(obs)['order'][0]=='down'
    obs=observation();obs['support']['finish']['x']=4
    assert decision(obs)['order'][0]=='none'
    obs['support']['continues']=False
    assert decision(obs)['order'][0]=='jump'


def test_air_return_uses_the_actual_rope_and_spent_jump_state():
    obs=observation('fall: 15');obs['jumps_used']=2
    assert decision(obs)['order'][0]=='down'
    del obs['support']
    assert decision(obs)['order'][0]=='none'
    obs['role']=[]
    with pytest.raises(ValueError):decision(obs)


def test_second_jump_and_its_native_fall_history_do_not_request_a_third_jump():
    obs=observation('jump2: 16');obs['hazards']=[hazard(2,1)]
    assert decision(obs)['order'][0]!='jump'and decision(obs)['jumps_used']==2
    obs['state']['physics']='fall: 15';obs['last_physics']='jump2: 16'
    assert decision(obs)['order'][0]!='jump'and decision(obs)['jumps_used']==2
