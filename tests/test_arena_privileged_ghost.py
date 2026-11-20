"""Original GhostFire pulses, spawn timing, and pooled-instance lineage."""
from copy import deepcopy,copy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import ghost_radius,pending_curve,curve_counterfactual,curve_range
from arena_privileged_model import PlayerModel,hazard_forecasts,rows
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-ghost.json').read_text())


def test_original_birth_to_live_hurt_shapes_are_enclosed():
    case=DATA['pending'];o=case['before'];original=deepcopy(o)
    times=np.array([0.,*[q['seconds']for q in case['after']]])
    hs,reason=pending_curve(case['entry'],times,o,PlayerModel(o));assert not reason
    assert hs[0].kind=='EnemyGhostFire';checked=0
    for i,q in enumerate(case['after'],1):
        for c in rows(q['colliders']):
            if not c.get('damage_kind')or not c['enabled']or not c['active']:continue
            center=np.array([c['center'][a]for a in('x','y')]);extent=np.array([c['extents'][a]for a in('x','y')])
            assert np.all(abs(center-hs[0].centers[i])+extent<=hs[0].extents[i]+.0002);checked+=1
    assert checked and o==original


def test_live_original_future_spheres_stay_inside_pulse_envelope():
    assert DATA['live']
    for case in DATA['live']:
        o=case['before'];target=case['enemy'];times=np.array([q['seconds']for q in case['after']])
        hs,missing=hazard_forecasts(o,times,PlayerModel(o));assert not any(m['id']==target['id']for m in missing)
        h=next(h for h in hs if h.enemy==target['id']);assert h.geometry=='sphere'and h.approximate
        # The exported transforms allow a tight root envelope, rather than
        # adding lengths of cancelling offsets or freezing the current pulse.
        assert .51<h.extents[0,0]<.53
        for i,q in enumerate(case['after']):
            e=q['enemy'];assert e['info_identity']==target['info_identity']and e['fields']['m_index']==target['fields']['m_index']
            for c in e['colliders']:
                if not c.get('damage_kind')or not c['enabled']or not c['active']:continue
                center=np.array([c['center'][a]for a in('x','y')]);radius=max(c['extents'][a]for a in('x','y','z'))
                assert np.linalg.norm(center-h.centers[i])+radius<=h.extents[i,0]+h.padding+.0002


@pytest.mark.parametrize('change',['owner','shape','callback','sprite_callback','weighted','truncated','easing','script','root_script','hotfix','body','rotation','chain','scale_missing','transform'])
def test_unknown_geometry_or_tween_is_explicitly_rejected(change):
    g=deepcopy(DATA['live'][0]['enemy']['ghost_geometry']);c=g['colliders'][0];n=g['nodes'][0];t=n['scales'][0]
    if change=='owner':c['owner_bound']=False
    if change=='shape':c['type']='BoxCollider'
    if change=='callback':t['callbacks_clear']=False
    if change=='sprite_callback':n['tweens'][0]['callbacks_clear']=False
    if change=='weighted':t['curve'][0]['weighted_mode']='Both: 3'
    if change=='truncated':t['curve_truncated']=True
    if change=='easing':t['fields']['method']='spring: 9'
    if change=='script':n['scripts'].append('UnknownMover')
    if change=='root_script':g['component_types'].append('uTools.uTweenScale')
    if change=='hotfix':g['native_geometry']=False
    if change=='body':n['physics']['kinematic']=False
    if change=='rotation':n['rotation']['w']=.8
    if change=='chain':c['chain']=[-1]
    if change=='scale_missing':n['scales']=[]
    if change=='transform':n['transform_type']='RectTransform'
    radius,reason=ghost_radius(g);assert radius is None and reason


def test_scale_curve_overshoot_is_enclosed_beyond_authored_endpoints():
    g=deepcopy(DATA['live'][0]['enemy']['ghost_geometry']);baseline=ghost_radius(g)[0]
    for node in g['nodes']:
        t=node['scales'][0];t['curve'][0]['out_tangent']=16.;t['curve'][1]['in_tangent']=-16.
        assert curve_range(t['curve'])[1]>4.
    radius,reason=ghost_radius(g);assert not reason and radius>baseline+.05


def test_legacy_missing_quaternion_is_conservative_instead_of_assuming_identity():
    g=deepcopy(DATA['live'][0]['enemy']['ghost_geometry']);tight=ghost_radius(g)[0]
    for node in g['nodes']:node.pop('rotation')
    loose,reason=ghost_radius(g);assert not reason and loose>tight+.3


def test_missing_geometry_channel_does_not_keep_frozen_current_size():
    o=deepcopy(DATA['live'][0]['before']);target=DATA['live'][0]['enemy']
    next(e for e in o['enemies']if e['id']==target['id']).pop('ghost_geometry')
    hs,missing=hazard_forecasts(o,np.linspace(0.,1.,121),PlayerModel(o))
    assert not any(h.enemy==target['id']for h in hs)
    assert any(m['id']==target['id']and m['reason']=='ghost_original_geometry_missing'for m in missing)


def test_pending_counterfactual_uses_pre_key_birth_not_nominal_later_phase():
    case=DATA['pending'];origin=case['before'];o=case['first_live'];elapsed=o['state']['time']-origin['state']['time']
    times=np.linspace(0.,1.,121);query=elapsed+times;mesh=np.unique(np.r_[np.linspace(0.,query[-1],361),query])
    prior=PlayerModel(origin);_,motors,valid=prior.trajectory(mesh);assert valid
    indices=np.searchsorted(mesh,query);current=PlayerModel(o);current.initial=copy(motors[indices[0]])
    target=next(e for e in o['enemies']if e['info_identity']==case['entry']['info_identity'])
    assert curve_counterfactual(target,times,o,current)==(None,False)
    current._reference_history=dict(model=prior,times=mesh,motors=motors,indices=indices,offset=elapsed)
    hs,missing=hazard_forecasts(o,times,current,[motors[i]for i in indices])
    assert not any(m['id']==target['id']for m in missing)
    h=next(h for h in hs if h.enemy==target['id']);assert h.geometry=='aabb'and 'actual pre-key world'in h.source
    for c in target['colliders']:
        if not c.get('damage_kind')or not c['enabled']or not c['active']:continue
        center=np.array([c['center'][a]for a in('x','y')]);extent=np.array([c['extents'][a]for a in('x','y')])
        assert np.all(abs(center-h.centers[0])+extent<=h.extents[0]+.0002)


def test_pending_random_height_and_all_sine_phases_are_conservatively_bounded():
    case=deepcopy(DATA['pending']);entry=case['entry'];o=case['before'];c=entry['custom']
    c['_rangeRandomY']=.7;c['_angularSpeed']=-2.3;c['_speedX']=-3.;c['_initalPhaseRadian']=.9;c['_amplitude']=2.7
    times=np.linspace(0.,1.8,217);hs,reason=pending_curve(entry,times,o,PlayerModel(o));assert not reason
    h=hs[0];spawn=np.array([entry['block_start'][a]+entry['info']['_localPosition'][a]for a in('x','y')])
    for delta in (-.7,0.,.7):
        for born in (0.,.15,.9,1.8):
            elapsed=np.maximum(0.,times-born);x=spawn[0]+c['_speedX']*elapsed
            y=spawn[1]+delta+c['_amplitude']*(np.sin(c['_initalPhaseRadian']+c['_angularSpeed']*elapsed)-np.sin(c['_initalPhaseRadian']))
            assert np.all(abs(np.column_stack((x,y))-h.centers)<=h.extents)


def test_per_observation_reuse_keeps_hazards_and_counterfactual_birth_guard():
    from unittest.mock import patch
    import arena_privileged_families as families
    o=DATA['live'][0]['before'];p=PlayerModel(o);times=np.linspace(0.,1.,121);cache={}
    baseline,missing=hazard_forecasts(o,times,p)
    with patch.object(families,'forecast',wraps=families.forecast)as native:
        first,first_missing=hazard_forecasts(o,times,p,forecast_cache=cache)
        calls=native.call_count
        second,second_missing=hazard_forecasts(o,times,p,forecast_cache=cache)
        assert native.call_count==calls
    assert first_missing==second_missing==missing
    for a,b,c in zip(baseline,first,second,strict=True):
        assert a.id==b.id==c.id and a.geometry==b.geometry==c.geometry
        for attribute in ('centers','extents','active'):
            assert np.array_equal(getattr(a,attribute),getattr(b,attribute))
            assert np.array_equal(getattr(a,attribute),getattr(c,attribute))
    # An earlier hypothetical key has no valid native birth lineage. Cached
    # nominal FlyToNinja motion must not make this unknown branch safe.
    projected=copy(p);projected.initial=copy(p.initial)
    hs,rejected=hazard_forecasts(o,times,projected,forecast_cache=cache)
    ghosts={e['id']for e in o['enemies']if e['type']=='EnemyGhostFire'and not e['fields']['_dead']}
    assert ghosts and not any(h.enemy in ghosts for h in hs)
    assert {r['id']for r in rejected if r['reason']=='curve_past_birth_activation_history_unbound'}==ghosts
    # A different observation cannot retain the previous clock or geometry.
    new=deepcopy(o);new['state']['time']+=.01
    fresh,why=hazard_forecasts(new,times,PlayerModel(new));reused,why2=hazard_forecasts(new,times,PlayerModel(new),forecast_cache=cache)
    assert why==why2 and cache['_observation']is new
    for a,b in zip(fresh,reused,strict=True):
        assert np.array_equal(a.centers,b.centers)and np.array_equal(a.extents,b.extents)
