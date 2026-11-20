"""Native generated thorns and movement contacts follow their parent's clock."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_families import brambles_path,brambles_child

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-brambles.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_original_activation_warning_stab_and_hold_contain_generated_boxes(case):
    o=case['before'];original=deepcopy(o);q=case['after']
    dt=q['state']['time']-o['state']['time'];times=np.linspace(0.,dt,round(dt*120)+1)
    hazards,missing=hazard_forecasts(o,times,PlayerModel(o))
    assert not missing and o==original
    assert {h.kind for h in hazards}=={'EnemyBramblesSingleThorn','EnemyBrambleCollider'}
    assert not o['role']['god']and not o['role']['mounted']
    for h in hazards:
        e=next(e for e in q['enemies']if e['id']==h.enemy)
        c=next(c for c in e['colliders']if c['id']==h.id)
        center=np.array([c['center'][a]for a in ('x','y')]);extent=np.array([c['extents'][a]for a in ('x','y')])
        assert np.all(abs(center-h.centers[-1])+extent<=h.extents[-1])
        assert h.geometry=='aabb'and h.approximate and h.quads is None
        assert h.interaction==(e['type']=='EnemyBrambleCollider')
        if h.interaction:assert 'damage_kind'not in c
        # Child MyFixedUpdate never updates this clock. It cannot be the
        # reference for predicting the parent's movement.
        assert e['fields']['_lastFixedUpdateTime']==0


@pytest.mark.parametrize('change,reason',[
    ('missing','brambles_child_original_live_parent'),
    ('pooled','brambles_child_original_live_parent'),
    ('outside_render','brambles_child_original_live_parent'),
    ('phase','brambles_original_action_sequence'),
    ('sequence','brambles_current_action_disagreement'),
    ('clock','brambles_original_parent_clock'),
    ('future_block','brambles_future_uninstantiated_blocks'),
    ('truncated','brambles_original_action_sequence'),
    ('render_rotation','brambles_unverified_render_transform'),
    ('geometry','brambles_child_original_planar_boxes'),
])
def test_unknown_owner_history_and_geometry_do_not_become_static_thorns(change,reason):
    o=deepcopy(DATA['cases'][0]['before']);owner,e=o['enemies'][:2]
    if change=='missing':o['enemies'].remove(owner)
    if change=='pooled':owner['info_identity']+=1
    if change=='outside_render':e['brambles_owner']['under_render']=False
    if change=='phase':owner['fields']['_currState']='Unknown: 99'
    if change=='sequence':owner['brambles']['action']['_moveOrStabSpeed']+=1
    if change=='clock':owner['fields']['_lastFixedUpdateTime']-=1
    if change=='future_block':owner['fields']['_totalBrambleBlockNum']+=1
    if change=='truncated':owner['brambles']['actions_truncated']=True
    if change=='render_rotation':owner['brambles']['render']['rotation']['z']=10
    if change=='geometry':e['colliders'][0]['depth_tilt']=True
    predicted,missing=brambles_child(e,np.array([0.,.5]),o,PlayerModel(o))
    assert predicted is None and missing==reason


def test_source_flip_ground_clamp_uses_original_one_point_eight_constant():
    # Source-contract variant; not an observed native clamp. The live case
    # reaches local maximum first; this variant exercises the other branch.
    o=deepcopy(DATA['cases'][2]['before']);owner=o['enemies'][0]
    owner['fields']['_groundY']=4.
    path,reason=brambles_path(owner,np.array([0.,.04]),o,PlayerModel(o))
    assert not reason
    # Parent 5.7 clamps renderer world Y to ground+1.8=5.8, which is
    # above its current 5.3. The source does not clamp to the visual tip.
    lo,hi,padding=path
    assert lo[-1,1]==pytest.approx(5.8-(5.7-.4),abs=.001)
    assert hi[-1,1]==pytest.approx(lo[-1,1],abs=.001)


def test_source_wait_after_back_does_not_invent_a_second_wait_duration():
    o=deepcopy(DATA['cases'][2]['before']);owner=o['enemies'][0]
    owner['fields'].update(_currState='Back: 4',_waitTime=0.)
    for action in [owner['brambles']['action'],*owner['brambles']['actions']]:
        action.update(_stabBackSpeed=100.,_toNextActionWaitTime=100.)
    # Back -> Wait keeps zero timer; the following tick starts another
    # warning. At .5s all permitted warning phases have started the stab.
    times=np.array([0.,.04,.5]);path,reason=brambles_path(owner,times,o,PlayerModel(o))
    assert not reason and path[1][-1,1]<0


def warning_binding():
    return dict(implementation='lua_fixed_coroutine',id='5',controllers=1,processing=True,truncated=False,
        matches=[dict(type='NewCoroutine',stack_count=1,fields=dict(ID=5,delayTime=.2,hasOwner=False,
            state='Running: 0',nowStep='FixedUpdate: 1',nextStep='FixedUpdate: 1'))])


def test_source_bound_pending_coroutine_narrows_legacy_warning_age_envelope():
    o=deepcopy(DATA['cases'][0]['before']);owner=o['enemies'][0]
    times=np.linspace(0.,.16,21);wide,reason=brambles_path(owner,times,o,PlayerModel(o))
    assert not reason
    owner['brambles']['warning']=warning_binding()
    narrow,reason=brambles_path(owner,times,o,PlayerModel(o))
    assert not reason
    assert wide[0][-1,1]<-1.
    assert narrow[0][-1,1]==narrow[1][-1,1]==0.


def test_native_logic_coroutine_positive_float_residue_costs_an_extra_tick():
    case=next(c for c in DATA['cases']if c['name']=='native_lua_float_residue')
    o=case['before'];owner=o['enemies'][0];warning=owner['brambles']['warning']
    assert warning['implementation']=='lua_fixed_coroutine'
    assert 0<warning['matches'][0]['fields']['delayTime']<1e-6
    assert warning['id']==str(warning['matches'][0]['fields']['ID'])
    path,reason=brambles_path(owner,np.array([0.,.001,.05]),o,PlayerModel(o))
    assert not reason and path[0][1,1]==path[1][1,1]==0
    assert path[0][-1,1]<0


@pytest.mark.parametrize('change',['missing','duplicate','owner','pause','queue','inactive','truncated','negative','late','pooled'])
def test_missing_or_unknown_original_coroutine_binding_is_explicit(change):
    o=deepcopy(DATA['cases'][0]['before']);owner=o['enemies'][0]
    warning=owner['brambles']['warning']=warning_binding();cf=warning['matches'][0]['fields']
    if change=='missing':warning['matches']=[]
    if change=='duplicate':warning['matches'].append(deepcopy(warning['matches'][0]))
    if change=='owner':cf['hasOwner']=True
    if change=='pause':cf['state']='Paused: 1'
    if change=='queue':cf['nextStep']='Update: 0'
    if change=='inactive':warning['processing']=False
    if change=='truncated':warning['truncated']=True
    if change=='negative':cf['delayTime']=-.01
    if change=='late':cf['delayTime']=1.
    if change=='pooled':cf['ID']=6
    path,reason=brambles_path(owner,np.array([0.,.5]),o,PlayerModel(o))
    assert path is None and reason=='brambles_original_warning_coroutine_binding'


def test_movement_contact_cannot_hide_behind_a_far_spawn_root():
    from arena_privileged_policy import InternalController
    o=deepcopy(DATA['cases'][0]['before']);owner,thorn,movement=o['enemies']
    x=o['state']['position']['x'];movement['position']['x']=x+1000
    movement['brambles_owner']['info_identity']+=1
    c=movement['colliders'][0];c['center']['x']=x
    c.pop('quad',None)
    decision=InternalController().decide(o)
    assert decision.reason=='unsupported_native_mechanism'
    assert any(v['id']==movement['id']for v in decision.evidence['unsupported_enemies'])
