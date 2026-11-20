"""Original rolling stones: activation, slope seams, reverse motion and pits."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
import arena_privileged_families as families

FIXTURE=json.loads((Path(__file__).parent/'fixtures/arena-privileged-rolling.json').read_text())


@pytest.mark.parametrize('case',FIXTURE['cases'],ids=lambda c:c['name'])
def test_original_rolling_states_and_collision_bounds(case):
    b,a=case['before'],case['after'];dt=a['state']['time']-b['state']['time'];p=PlayerModel(b)
    hs,missing=hazard_forecasts(b,np.linspace(0,dt,round(dt*120)+1),p)
    assert not missing and len(hs)==1
    h=hs[0];c=a['enemy']['colliders'][0]
    center=np.array([c['center'][x]for x in ('x','y')]);ext=np.array([c['extents'][x]for x in ('x','y')])
    assert np.all(abs(center-h.centers[-1])+ext<=h.extents[-1]+h.padding)
    assert h.active.all() and h.approximate
    if b['enemies'][0]['fields']['_enemyState']=='none: 0':assert h.geometry=='aabb'
    else:
        assert h.geometry=='sphere'
        assert np.linalg.norm(center-h.centers[-1])<.001
    if b['state']['health']!=a['state']['health']:
        assert case.get('scope') and case['name']=='resolved_before_instantiation'
    else:assert b['state']['health']==a['state']['health']>0
    assert not b['role']['god'] and not a['role']['god']
    assert not b['role']['mounted'] and not a['role']['mounted']
    assert b['enemies'][0]['info_identity']==a['enemy']['info_identity']


def observation(name='seam'):
    return deepcopy(next(c['before']for c in FIXTURE['cases']if c['name']==name))


def test_pooled_none_replaces_its_stale_prior_spawn_block_on_activation():
    case=next(c for c in FIXTURE['cases']if c['name']=='pooled_activation')
    e=case['before']['enemies'][0];actual=case['after']['enemy']
    assert e['rolling_support']['id']!=e['native_support']['id']
    assert e['position']['x']>e['rolling_support']['finish']['x']+50
    assert actual['rolling_support']['id']==e['native_support']['id']


def test_native_rock_crosses_a_segment_that_had_no_live_next_link_at_forecast_origin():
    case=next(c for c in FIXTURE['cases']if c['name']=='resolved_before_instantiation')
    e=case['before']['enemies'][0];actual=case['after']['enemy']
    assert e['rolling_chain_truncated'] is False
    assert actual['rolling_support']['id']not in {b['id']for b in e['rolling_blocks']}


@pytest.mark.parametrize('change,reason',[
    ('direction','rolling_original_run_direction'),
    ('shape','rolling_original_root_sphere'),
    ('support','rolling_current_block_missing'),
    ('origin','rolling_native_chain_origin'),
    ('cycle','rolling_discontinuous_native_chain'),
    ('ready','rolling_ready_rebound_unverified'),
    ('spatial','rolling_spatial_velocity'),
    ('clock','rolling_original_fixed_clock'),
    ('lookup','rolling_native_lookup_range_missing'),
])
def test_unproved_shapes_clocks_and_terrain_branches_stay_explicit(change,reason):
    b=observation();e=b['enemies'][0]
    if change=='direction':b['camera']['direction']=-1
    if change=='shape':e['colliders'][0]['damage_kind']='attack_module'
    if change=='support':e.pop('rolling_support')
    if change=='origin':e['rolling_support']['id']+=1
    if change=='cycle':e['rolling_blocks'][-1]['start']['x']+=2
    if change=='ready':e['fields']['_readyToFall']=True
    if change=='spatial':e['fields']['_velocity']['z']=1
    if change=='clock':e['fields']['_lastFixedUpdateTime']-=.04
    if change=='lookup':b['role']['rules'].pop('ground_lengthen')
    result,missing=families.rolling(e,np.linspace(0,.5,61),b,PlayerModel(b))
    assert result is None and missing==reason


def test_original_edge_needs_next_ground_identity_instead_of_an_infinite_slope():
    b=observation();e=b['enemies'][0];e['rolling_blocks']=[e['rolling_support']];b['terrain']=[]
    hs,missing=hazard_forecasts(b,np.linspace(0,.5,61),PlayerModel(b))
    assert not hs and missing[0]['reason']=='rolling_native_next_block_missing'


def test_resolved_continuation_can_bound_a_not_yet_spawned_native_segment_without_mutating_input():
    b=observation();e=b['enemies'][0];e['rolling_blocks']=[e['rolling_support']]
    e['rolling_chain_truncated']=False
    original=deepcopy(b)
    hs,missing=hazard_forecasts(b,np.linspace(0,.5,61),PlayerModel(b))
    assert not missing and hs
    assert b==original
    # A cyclic/incomplete live graph is not the same as an absent future link.
    e['rolling_chain_truncated']=True
    hs,missing=hazard_forecasts(b,np.linspace(0,.5,61),PlayerModel(b))
    assert not hs and missing[0]['reason']=='rolling_native_next_block_missing'


def test_terminal_native_wall_stop_keeps_the_hurt_sphere_present():
    b=observation();e=b['enemies'][0];e['fields']['_enemyState']='stop: 5'
    # A stationary physical root still render-interpolates from its prior
    # position for the first partial tick; use already settled history here.
    e['fields']['_lastPosition']=deepcopy(e['position'])
    e['fields']['_secondLastPosition']=deepcopy(e['position'])
    hs,missing=hazard_forecasts(b,np.linspace(0,1.8,217),PlayerModel(b))
    assert not missing and len(hs)==1 and hs[0].active.all()
    np.testing.assert_allclose(hs[0].centers,hs[0].centers[:1].repeat(217,axis=0),atol=1e-6)


def test_rejected_activation_branch_cannot_be_discarded_from_the_envelope(monkeypatch):
    b=observation('activation');e=b['enemies'][0];original=families.rolling_path;calls=[]
    def reject_second(*args,**kwargs):
        calls.append(args[-1])
        if len(calls)==2:return None,'rolling_native_next_block_missing'
        return original(*args,**kwargs)
    monkeypatch.setattr(families,'rolling_path',reject_second)
    result,reason=families.rolling(e,np.linspace(0,.5,61),b,PlayerModel(b))
    assert len(calls)==2 and result is None and reason=='rolling_native_next_block_missing'
