"""Original bamboo segment quantization and moving parent collider geometry."""
from copy import deepcopy
import json,math
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import pending_thorn,pending_thorn_vertices,pending_hook_phase
from arena_privileged_model import PlayerModel,rows
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-pending-thorn.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'])
def test_original_reset_parent_transforms_reproduce_first_live_box(case):
    o=case['before'];enemy=case['reset_enemy']
    template=o['spawn_templates']['hooks']['EnemyBambooThorn']
    vertices=pending_thorn_vertices(case['entry'],template)[:,:2]
    angle=math.radians(enemy['rotation_z']);co,si=math.cos(angle),math.sin(angle)
    points=vertices@np.array([[co,-si],[si,co]]).T+np.array([enemy['position'][a]for a in('x','y')])
    for c in rows(enemy['colliders']):
        if not c.get('damage_kind'):continue
        actual=np.array([[v[a]for a in('x','y')]for v in c['quad']])
        assert np.max(abs(actual.min(axis=0)-points.min(axis=0)))<.001
        assert np.max(abs(actual.max(axis=0)-points.max(axis=0)))<.001


@pytest.mark.parametrize('case',DATA['cases'])
def test_bounded_birth_and_activation_include_actual_later_corners(case):
    o=case['before'];original=deepcopy(o)
    times=np.unique(np.r_[np.linspace(0,1.8,217),[q['seconds']for q in case['after']]])
    p=PlayerModel(o);_,motors,valid=p.trajectory(times);assert valid
    hs,reason=pending_hook_phase(case['entry'],times,o,p,motors,{})
    assert not reason and hs
    if case['narrow']:assert 'bounded role-distance birth'in hs[0].source
    for q in case['after']:
        i=int(np.searchsorted(times,q['seconds']));assert hs[0].active[i]
        actual=np.array([[v[a]for a in('x','y')]for v in q['collider']['quad']])
        assert np.all(abs(actual-hs[0].centers[i])<=hs[0].extents[i]+.0002)
    assert o==original


@pytest.mark.parametrize('change',['chain','callback','animation','extra_script','new_box','owner','rotation','custom','spawn','scale'])
def test_unknown_initialization_and_parent_changes_remain_explicit(change):
    case=deepcopy(DATA['cases'][0]);o=case['before'];entry=case['entry'];t=o['spawn_templates']['hooks']['EnemyBambooThorn']
    if change=='chain':t['chain_complete']=False
    if change=='callback':t['callbacks_clear']=False
    if change=='animation':t['animated_tree']=True
    if change=='extra_script':t['component_types'].append('UnknownMovement')
    if change=='new_box':t['colliders'][0]['under_part']=False
    if change=='owner':t['colliders'][0]['owner_bound']=False
    if change=='rotation':t['chain'][0]['rotation']['x']=30.
    if change=='custom':entry['custom_projection']['complete']=False
    if change=='spawn':t['native_spawn']=False
    if change=='scale':entry['info']['_localScale']['x']=0.
    hs,reason=pending_thorn(entry,np.linspace(0,1.8,217),o)
    assert hs is None and reason.startswith('pending_thorn_')


def test_quantized_radius_changes_bamboo_parent_and_collider_together():
    case=deepcopy(DATA['cases'][0]);entry=case['entry'];t=case['before']['spawn_templates']['hooks']['EnemyBambooThorn']
    entry['custom']['_radius']=9.;a=pending_thorn_vertices(entry,t)
    entry['custom']['_radius']=9.1;b=pending_thorn_vertices(entry,t)
    assert np.array_equal(a,b)
    entry['custom']['_radius']=1.64;small=pending_thorn_vertices(entry,t)
    # Collider's upper end is preserved while the bottom parent moves down;
    # changing a single head offset cannot reproduce this native reset.
    assert np.max(abs(a[:,1]-small[:,1]))>8.
    assert abs(a[:,1].max()-small[:,1].max())<.00001
