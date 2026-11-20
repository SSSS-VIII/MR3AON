"""Original hover box and acceleration, with unknown birth time."""
from copy import deepcopy,copy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import pending_suspend,pending_motion_history

def suspend_counterfactual(enemy,times,observation,player):
    return pending_motion_history(enemy,times,observation,player,pending_suspend,{'stay','move'},'_state')
from arena_privileged_model import PlayerModel,rows
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-pending-suspend.json').read_text())


def test_original_birth_to_live_boxes_stay_inside_source_bound():
    case=DATA['cases'][0];o=case['before'];original=deepcopy(o)
    times=np.array([0.,*[q['seconds']for q in case['after']]])
    hs,reason=pending_suspend(case['entry'],times,o,PlayerModel(o));assert not reason
    h=hs[0];checked=0
    for i,q in enumerate(case['after'],1):
        for c in rows(q['colliders']):
            if not c.get('damage_kind')or not c['enabled']:continue
            center=np.array([c['center'][a]for a in('x','y')]);extent=np.array([c['extents'][a]for a in('x','y')])
            assert np.all(abs(center-h.centers[i])+extent<=h.extents[i]+.0002);checked+=1
    assert checked and o==original


@pytest.mark.parametrize('change',['render','random','script','hook','animation','root','shape','projection'])
def test_unbound_variant_or_geometry_is_not_silently_ignored(change):
    case=deepcopy(DATA['cases'][0]);o=case['before'];entry=case['entry'];t=o['spawn_templates']['suspends']['EnemySuspendBalloon']
    if change=='render':entry['custom']['_render']=1
    if change=='random':entry['custom']['_rangeRandomY']=1
    if change=='script':t['component_types'].append('UnknownMover')
    if change=='hook':t['native_initialization']=False
    if change=='animation':t['animated_tree']=True
    if change=='root':t['colliders'][0]['direct_root']=False
    if change=='shape':t['colliders'][0]['type']='CapsuleCollider'
    if change=='projection':entry['custom_projection']['complete']=False
    hs,reason=pending_suspend(entry,np.linspace(0,1.8,217),o,PlayerModel(o))
    assert hs is None and reason.startswith('pending_suspend_')


def test_counterfactual_spawn_uses_actual_pre_key_world_or_rejects_missing_history():
    case=DATA['cases'][0];o=case['before'];entry=case['entry'];times=np.linspace(0,1.8,217)
    prior=PlayerModel(o);_,motors,valid=prior.trajectory(times);assert valid
    current=copy(prior);current.initial=copy(prior.initial)
    enemy=dict(id=123,type='EnemySuspend',info_identity=entry['info_identity'],info=entry['info'],
        custom=entry['custom'],position=o['state']['position'],fields=dict(m_index=9,_state='move: 2'),
        colliders=[dict(id=456,damage_kind='enemy_callback')])
    assert suspend_counterfactual(enemy,times,o,current)==(None,False)
    current._reference_history=dict(model=prior,times=times,motors=motors,indices=np.arange(len(times)),offset=0.)
    prediction,independent=suspend_counterfactual(enemy,times,o,current)
    assert prediction is not None and not independent and 456 in prediction[1]
    prior.observation=deepcopy(o);prior.observation['pending_enemies']=[]
    assert suspend_counterfactual(enemy,times,o,current)==(None,False)



def test_live_counterfactual_birth_keeps_its_rectangular_enclosure_in_the_model():
    from arena_privileged_model import hazard_forecasts
    case=DATA['cases'][0];origin=case['before'];observation=case['first_live']
    elapsed=observation['state']['time']-origin['state']['time'];times=np.linspace(0,1.,121)
    query=elapsed+times;mesh=np.unique(np.r_[np.linspace(0.,query[-1],241),query])
    prior=PlayerModel(origin);_,motors,valid=prior.trajectory(mesh);assert valid
    indices=np.searchsorted(mesh,query);current=PlayerModel(observation);current.initial=copy(motors[indices[0]])
    current._reference_history=dict(model=prior,times=mesh,motors=motors,indices=indices,offset=elapsed)
    hs,missing=hazard_forecasts(observation,times,current,[motors[i]for i in indices])
    targets=[e for e in rows(observation['enemies'])if e['info_identity']==case['entry']['info_identity']]
    ids={e['id']for e in targets}
    assert ids and not any(v['id']in ids for v in missing)
    born=[h for h in hs if h.enemy in ids];assert born
    for h in born:
        assert h.geometry=='aabb'and 'actual pre-key world'in h.source
        c=next(c for e in targets for c in e['colliders']if c['id']==h.id)
        center=np.array([c['center'][a]for a in('x','y')]);extent=np.array([c['extents'][a]for a in('x','y')])
        assert np.all(abs(center-h.centers[0])+extent<=h.extents[0]+.0002)



def test_zero_amplitude_with_original_acceleration_still_moves():
    case=deepcopy(DATA['cases'][0]);o=case['before'];entry=case['entry']
    assert entry['custom']['_amplitude']==0 and o['spawn_templates']['suspends']['EnemySuspendBalloon']['acc']==1
    times=np.linspace(0,1.8,217);moving=pending_suspend(entry,times,o,PlayerModel(o))[0][0]
    o['spawn_templates']['suspends']['EnemySuspendBalloon']['acc']=0.
    static=pending_suspend(entry,times,o,PlayerModel(o))[0][0]
    assert moving.extents[-1,1]>static.extents[-1,1]+1.
    assert np.ptp(static.centers[:,1])<.0001
