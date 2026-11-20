"""Original pre-birth curve clock, including real rope flips and old worlds."""
from copy import deepcopy,copy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import pending_curve,pending_curve_phase,curve_counterfactual
from arena_privileged_model import PlayerModel,hazard_forecasts,rows
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-curve-phase.json').read_text())


@pytest.mark.parametrize('trace',DATA['traces'],ids=lambda t:t['version'])
def test_original_future_moving_ghosts_are_inside_bounded_birth_clock(trace):
    o=trace['before'];original=deepcopy(o)
    for case in trace['cases']:
        actual_times=np.array([q['seconds']for q in case['after']])
        times=np.unique(np.r_[np.linspace(0.,1.8,217),actual_times]);indices=np.searchsorted(times,actual_times)
        model=PlayerModel(o)
        operations=[(e['frame']/60,e['action'])for e in trace['events']if e['frame']/60<=times[-1]]
        _,motors,valid=model.trajectory(times,operations);assert valid
        hs,reason=pending_curve_phase(case['entry'],times,o,model,motors,{})
        assert not reason and hs and 'bounded role-distance'in hs[0].source
        broad=pending_curve(case['entry'],times,o,model)[0][0];h=hs[0]
        assert h.extents[-1,1]<broad.extents[-1,1]-.5
        for i,q in zip(indices,case['after'],strict=True):
            for c in rows(q['colliders']):
                if not c.get('damage_kind')or not c['enabled']or not c['active']:continue
                center=np.array([c['center'][a]for a in('x','y')]);extent=np.array([c['extents'][a]for a in('x','y')])
                assert h.active[i]and np.all(abs(center-h.centers[i])+extent<=h.extents[i]+.0002)
    assert o==original


@pytest.mark.parametrize('change',['parent','vertical','camera','clock','pop'])
def test_unproven_birth_or_camera_keeps_the_complete_lifetime_envelope(change):
    trace=deepcopy(DATA['traces'][0]);o=trace['before'];entry=trace['cases'][0]['entry']
    if change=='parent':entry['source']='resolved_uninstantiated_block'
    if change=='vertical':entry['vertical_gate']=True
    if change=='camera':o['camera']['fields']['_cameraShift']=True
    if change=='clock':
        o['state']['time']=200000.;o['role']['fields']['_lastFixedUpdateTime']=200000.
    model=PlayerModel(o);times=np.linspace(0.,1.8,217);_,motors,valid=model.trajectory(times)
    if change=='pop':model.initial.mode='popup'
    h,reason=pending_curve_phase(entry,times,o,model,motors,{})
    baseline,why=pending_curve(entry,times,o,model)
    assert not reason and not why and h[0].source==baseline[0].source
    assert np.array_equal(h[0].centers,baseline[0].centers)and np.array_equal(h[0].extents,baseline[0].extents)


@pytest.mark.parametrize('trace',DATA['traces'],ids=lambda t:t['version'])
def test_later_live_ghost_uses_actual_pre_key_clock_with_aabb_preserved(trace):
    case=trace['cases'][0];origin=trace['before'];o=case['first_live'];elapsed=o['state']['time']-origin['state']['time']
    times=np.linspace(0.,1.2,145);query=elapsed+times;mesh=np.unique(np.r_[np.linspace(0.,query[-1],241),query])
    prior=PlayerModel(origin);operations=[(e['frame']/60,e['action'])for e in trace['events']if e['frame']/60<=mesh[-1]]
    _,motors,valid=prior.trajectory(mesh,operations);assert valid
    ix=np.searchsorted(mesh,query);current=PlayerModel(o);current.initial=copy(motors[ix[0]])
    enemy=next(e for e in o['enemies']if e['info_identity']==case['entry']['info_identity'])
    assert curve_counterfactual(enemy,times,o,current)==(None,False)
    current._reference_history=dict(model=prior,times=mesh,motors=motors,indices=ix,offset=elapsed)
    hs,missing=hazard_forecasts(o,times,current,[motors[i]for i in ix])
    assert not any(m['id']==enemy['id']for m in missing)
    h=next(h for h in hs if h.enemy==enemy['id']);assert h.geometry=='aabb'and 'actual pre-key world'in h.source
    assert h.extents[-1,1]<2.
    for c in enemy['colliders']:
        if not c.get('damage_kind')or not c['enabled']or not c['active']:continue
        center=np.array([c['center'][a]for a in('x','y')]);extent=np.array([c['extents'][a]for a in('x','y')])
        assert np.all(abs(center-h.centers[0])+extent<=h.extents[0]+.0002)


def test_bound_phase_is_recomputed_without_a_cached_nominal_birth_for_earlier_key():
    trace=DATA['traces'][0];o=trace['before'];entry=trace['cases'][0]['entry'];times=np.linspace(0.,1.8,217)
    actual=PlayerModel(o);_,motors,valid=actual.trajectory(times);assert valid
    cache={};ordinary,reason=pending_curve_phase(entry,times,o,actual,motors,cache)
    assert not reason and 'bounded role-distance'in ordinary[0].source
    earlier=copy(actual);earlier.initial=copy(actual.initial)
    conservative,reason=pending_curve_phase(entry,times,o,earlier,motors,cache)
    assert not reason and 'all render spheres and possible birth'in conservative[0].source
    assert conservative[0].extents[-1,1]>ordinary[0].extents[-1,1]+.5


def test_existing_waiting_object_cannot_borrow_a_repeated_info_pending_birth():
    case=deepcopy(DATA['traces'][0]['cases'][0]);origin=deepcopy(DATA['traces'][0]['before']);o=case['first_live']
    enemy=next(e for e in o['enemies']if e['info_identity']==case['entry']['info_identity'])
    # Repeated source blocks can retain the same EnemyInfo identity. If this
    # exact native object already waited in the old world, a queued repeat
    # cannot supply its activation clock, even though the info fields match.
    waiting=deepcopy(enemy);waiting['fields']['_currState']='None: 0';origin['enemies']=[waiting]
    elapsed=o['state']['time']-origin['state']['time'];times=np.linspace(0.,1.,121);query=elapsed+times
    mesh=np.unique(np.r_[np.linspace(0.,query[-1],241),query]);prior=PlayerModel(origin)
    _,motors,valid=prior.trajectory(mesh);assert valid
    ix=np.searchsorted(mesh,query);current=PlayerModel(o);current.initial=copy(motors[ix[0]])
    current._reference_history=dict(model=prior,times=mesh,motors=motors,indices=ix,offset=elapsed)
    assert curve_counterfactual(enemy,times,o,current)==(None,False)


def test_stationary_root_keeps_its_verified_enclosure_without_camera_clock_work(monkeypatch):
    import arena_privileged_families as families
    trace=deepcopy(DATA['traces'][0]);o=trace['before'];entry=trace['cases'][0]['entry']
    entry['custom']['_speedX']=0.;entry['custom']['_angularSpeed']=0.
    p=PlayerModel(o);times=np.linspace(0.,1.8,217);_,motors,valid=p.trajectory(times);assert valid
    def unexpected(*args,**kwargs):raise AssertionError('Static root does not read the camera to move')
    monkeypatch.setattr(families,'camera_x_bounds',unexpected)
    hs,why=pending_curve_phase(entry,times,o,p,motors,{});baseline,why2=pending_curve(entry,times,o,p)
    assert not why and not why2 and np.array_equal(hs[0].extents,baseline[0].extents)


def test_explicitly_changed_spawn_implementation_is_not_an_unknown_clock_only():
    trace=deepcopy(DATA['traces'][0]);o=trace['before'];entry=trace['cases'][0]['entry']
    o['spawn_templates']['curves']['EnemyGhostFire']['native_spawn']=False
    p=PlayerModel(o);times=np.linspace(0.,1.8,217);_,motors,valid=p.trajectory(times);assert valid
    hs,reason=pending_curve_phase(entry,times,o,p,motors,{})
    assert hs is None and reason=='pending_curve_unverified_spawn_path'
