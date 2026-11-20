"""Conservative native hook head closure across actual birth and swing phases."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import pending_hook,forecast

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-pending-hook.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'])
def test_before_birth_full_turn_shape_contains_native_head_after_reset_and_swing(case):
    original=deepcopy(case);times=np.array([0.,.1,1.,1.8]);hs,reason=pending_hook(case['entry'],times,case['observation'])
    assert reason is None and hs[0].active.all()and hs[0].geometry=='sphere'
    h=hs[0]
    for later in case['after']:
        c=later['collider'];points=np.array([[p[a]for a in('x','y')]for p in c['quad']])
        assert np.linalg.norm(points-h.centers[-1],axis=1).max()<=h.extents[-1,0]+.0002
    assert case==original


@pytest.mark.parametrize('change',['prefab','hook','animated','script','parent','head_rotation','owner',
                                   'pole','vertices','custom','source','rotation','radius','scale','callback','gravity','physics','binding'])
def test_unknown_head_initialization_and_new_damage_shapes_remain_explicit(change):
    c=deepcopy(DATA['cases'][0]);e=c['entry'];o=c['observation'];t=o['spawn_templates']['hooks']['EnemyGoldHook']
    if change=='prefab':t['missing']=True
    if change=='hook':t['native_initialization']=False
    if change=='animated':t['animated_tree']=True
    if change=='script':t['component_types'].append('ExtraMove')
    if change=='parent':t['parent_identity']=False
    if change=='head_rotation':t['head_rotation']['y']=1
    if change=='owner':t['colliders'][0]['owner_bound']=False
    if change=='pole':t['colliders'][0]['under_pole']=True
    if change=='vertices':t['colliders'][0]['vertices'].pop()
    if change=='custom':e['custom_projection']['complete']=False
    if change=='source':e['source']='authored_minus_live'
    if change=='rotation':e['info']['_localEulerAngles']['x']=45
    if change=='radius':e['custom']['_radius']=float('nan')
    if change=='scale':e['info']['_localScale']['x']=0.
    if change=='callback':t['callbacks_clear']=False
    if change=='gravity':t['gravity']=True
    if change=='physics':t['kinematic']=False
    if change=='binding':e['info']['baseID']=1
    hs,reason=pending_hook(e,np.array([0.,1.8]),o)
    assert hs is None and reason.startswith('pending_hook_')


def test_native_radius_clamp_and_unknown_birth_clock_never_shrink_the_head_to_zero():
    c=deepcopy(DATA['cases'][0]);e=c['entry'];e['custom']['_radius']=.1;e['source']='resolved_uninstantiated_block'
    hs,reason=pending_hook(e,np.array([0.,1.8]),c['observation'])
    assert not reason and hs[0].extents.min()>2.


@pytest.mark.parametrize('kind',['EnemyHook','EnemyBambooThorn'])
@pytest.mark.parametrize('initial,candidate',[('popfall',None),('runonline',[SimpleNamespace(mode='popup')])])
def test_waiting_live_pendulum_camera_is_not_assumed_constant_speed_during_spring(kind,initial,candidate):
    e=dict(type=kind,fields=dict(_enemyState='none: 1'),custom={})
    result,reason=forecast(e,np.array([0.,1.8]),{},SimpleNamespace(initial=SimpleNamespace(mode=initial)),candidate)
    assert result is None and reason=='spring_pop_camera_transition_not_validated'


@pytest.mark.parametrize('kind',['EnemyHook','EnemyBambooThorn'])
def test_pending_spring_forces_original_waiting_camera_guards_to_be_recomputed(monkeypatch,kind):
    import arena_privileged_policy as policy
    o=json.loads((Path(__file__).parent/'fixtures/arena-privileged-static-pickups.json').read_text())['observation']
    o['pending_enemies']=[]
    o['enemies']=[dict(id=1,type=kind,colliders=[],custom={},fields=dict(_dead=False,_isRecycled=False))]
    def contract(observation,times,player,trajectory_states=None,**kwargs):
        if trajectory_states is not None and any(m.mode in ('popup','popfall')for m in trajectory_states):
            return [],[dict(id=1,type=kind,reason='spring_pop_camera_transition_not_validated')]
        return [],[]
    monkeypatch.setattr(policy,'hazard_forecasts',contract)
    result=policy.InternalController().decide(o)
    assert result.evidence['coupled_forecasts']
    assert result.reason!='native_corridor_clear'and not result.evidence['coast']['safe']
