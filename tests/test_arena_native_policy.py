from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab'))
from native_policy import decision,refine
from arena_checkpoint_errors import NativeIntervalError


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


def test_native_second_fall_recovers_the_rope_instead_of_waiting_with_spent_jumps():
    obs=observation('fall2: 17');obs.pop('jumps_used')
    proposed=decision(obs)
    assert proposed['jumps_used']==2
    assert proposed['order'][0]=='down'
    assert proposed['reason']=='recover_original_rope_jump_budget'
    obs['hazards']=[hazard(2,1)]
    assert decision(obs)['order'][0]!='jump'


class TrajectoryOracle:
    def __init__(self,outcome):
        self.outcome=outcome
        self.data=dict(state=dict(health=5000,episodeFrame=10),rng=17,collider='original')
        self.saved=deepcopy(self.data);self.calls=[]
    def step(self,ticks,action):
        self.calls.append((ticks,action))
        self.data.update(rng=99,collider='future');self.data['state']['episodeFrame']+=ticks
        if self.outcome=='damage':self.data['state']['health']=4750
        job=dict(after=deepcopy(self.data['state']),terminated=self.outcome=='terminated')
        if self.outcome=='invalid':raise NativeIntervalError('10 ticks overshot',job)
        if self.outcome=='error':raise RuntimeError('native forecast failed')
        return job
    def restore(self,point):
        assert point==7
        self.data=deepcopy(self.saved)
        return dict(ms=2)
    def call(self,operation):
        assert operation=='state'
        return deepcopy(self.data['state'])


@pytest.mark.parametrize('outcome,reason,expected',[
    ('safe','airborne_native_threat','none'),
    ('damage','original_jump_already_clears_native_volumes','jump'),
    ('terminated','original_jump_already_clears_native_volumes','jump')])
def test_original_trajectory_overrides_instantaneous_height_and_restores_everything(outcome,reason,expected):
    oracle=TrajectoryOracle(outcome)
    obs=dict(state=deepcopy(oracle.data['state']))
    proposal=dict(phase='jump',reason=reason,order=['jump','none','down'])
    result=refine(oracle,7,obs,proposal)
    assert result['order'][0]==expected and oracle.calls==[(10,'none')]
    assert oracle.data==oracle.saved
    assert result['original_trajectory_forecast']['safe']==(outcome=='safe')
    assert proposal['reason']==reason  # Retained current observation is not rewritten.


def test_invalid_or_failed_native_forecast_cannot_certify_or_leave_the_guest_in_the_future():
    oracle=TrajectoryOracle('invalid')
    proposal=dict(phase='jump',reason='airborne_native_threat',order=['jump','down','none'])
    result=refine(oracle,7,dict(state=deepcopy(oracle.data['state'])),proposal)
    assert result['order']==proposal['order']and result['original_trajectory_forecast']['safe']is None
    assert oracle.data==oracle.saved
    oracle.outcome='error'
    with pytest.raises(RuntimeError,match='native forecast failed'):
        refine(oracle,7,dict(state=deepcopy(oracle.data['state'])),proposal)
    assert oracle.data==oracle.saved
