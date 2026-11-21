"""Real pending-to-born geometry, random-reset enclosure and pre-key lineage."""
from copy import deepcopy,copy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import pending_mace,mace_motion,pending_motion_history
from arena_privileged_model import PlayerModel,Hazard
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-pending-mace.json').read_text())


def contains(h,i,points):
    if h.geometry=='sphere':
        assert np.all(np.linalg.norm(points-h.centers[i],axis=1)<=h.extents[i,0]+h.padding+.00005)
    else:
        q=h.quads[i];edges=np.roll(q,-1,axis=0)-q
        area=np.sum(q[:,0]*np.roll(q[:,1],-1)-q[:,1]*np.roll(q[:,0],-1))
        for a,e in zip(q,edges):
            side=(e[0]*(points[:,1]-a[1])-e[1]*(points[:,0]-a[0]))*np.sign(area)
            assert np.all(side>=-(h.padding+.00005)*np.linalg.norm(e))


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['version'])
def test_native_original_pending_to_live_corners_are_enclosed_without_mutation(case):
    o=case['before'];before=deepcopy(o);times=np.unique(np.r_[np.linspace(0.,case['after'][-1]['seconds'],217),[r['seconds']for r in case['after']]])
    p=PlayerModel(o);_,motors,valid=p.trajectory(times);assert valid
    hs,why=pending_mace(case['entry'],times,o,p,motors,{})
    assert not why and hs
    assert hs[0].geometry==('sphere'if case['version']=='v376'else'obb')
    for row in case['after']:
        i=int(np.searchsorted(times,row['seconds']))
        assert hs[0].active[i]
        for c in row['enemy']['colliders']:
            if c.get('damage_kind')and c['active']and c['enabled']:
                contains(hs[0],i,np.array([[q['x'],q['y']]for q in c['quad']]))
    assert o==before


@pytest.mark.parametrize('change',['missing','hook','callback','animation','script','body','interpolation','child','shape','size','nan','owner','projection','custom','tilt','parent'])
def test_unverified_initialization_or_shape_is_not_empty_road(change):
    case=deepcopy(DATA['cases'][1]);o=case['before'];entry=case['entry'];t=o['spawn_templates']['maces']['EnemyMace']
    if change=='missing':t['missing']=True
    if change=='hook':t['native_spawn']=False
    if change=='callback':t['callbacks_clear']=False
    if change=='animation':t['animated_tree']=True
    if change=='script':t['component_types'].append('UnknownMover')
    if change=='body':t['physics']['gravity']=True
    if change=='interpolation':t['physics']['interpolation']='Interpolate: 1'
    if change=='child':t['colliders'][0]['direct_root']=False
    if change=='shape':t['colliders'][0]['type']='CapsuleCollider'
    if change=='size':t['colliders'][0]['size']['x']=-1.
    if change=='nan':t['colliders'][0]['center']['x']=float('nan')
    if change=='owner':entry['info']['createPlayerUID']=10
    if change=='projection':entry['custom_projection']['complete']=False
    if change=='custom':entry['custom']['unknown']=True
    if change=='parent':t['parent_axes']['x']['x']=2.
    if change=='tilt':entry['info']['_localEulerAngles']['x']=10.
    p=PlayerModel(o);times=np.linspace(0.,1.8,217);_,motors,_=p.trajectory(times)
    hs,why=pending_mace(entry,times,o,p,motors,{})
    assert hs is None and why.startswith('pending_mace_')


def test_born_counterfactual_reconstructs_actual_pre_key_world_not_current_nominal_clock():
    case=DATA['cases'][1];origin=case['before'];o=case['first_live'];entry=case['entry']
    enemy=next(e for e in o['enemies']if e['type']=='EnemyMace'and e['info_identity']==entry['info_identity'])
    elapsed=o['state']['time']-origin['state']['time'];times=np.linspace(0.,1.,121);query=elapsed+times
    mesh=np.unique(np.r_[np.linspace(0.,query[-1],301),query]);prior=PlayerModel(origin)
    _,motors,valid=prior.trajectory(mesh);assert valid
    ix=np.searchsorted(mesh,query);current=PlayerModel(o);current.initial=copy(motors[ix[0]])
    assert mace_motion(enemy,times,o,current)[1]=='mace_past_activation_history_unbound'
    current._reference_history=dict(model=prior,times=mesh,motors=motors,indices=ix,offset=elapsed)
    prediction,why=mace_motion(enemy,times,o,current)
    assert not why and 'birth propagated'in prediction[2]
    assert prediction[5]['mace_shapes']and prediction[5]['mace_shapes'][enemy['colliders'][0]['id']]['geometry']=='aabb'
    prior.observation=deepcopy(origin);prior.observation['pending_enemies']=[]
    assert mace_motion(enemy,times,o,current)[1]=='mace_past_activation_history_unbound'


def test_history_union_preserves_each_forecasts_numeric_padding():
    case=DATA['cases'][1];o=case['before'];entry=case['entry'];times=np.array([0.,.1])
    prior=PlayerModel(o);_,motors,_=prior.trajectory(times);current=copy(prior);current.initial=copy(prior.initial)
    current._reference_history=dict(model=prior,times=times,motors=motors,indices=np.arange(2),offset=0.)
    enemy=dict(id=123,type='EnemyMace',info_identity=entry['info_identity'],info=entry['info'],custom=entry['custom'],
        fields=dict(_enemyState='rotation: 0',m_index=999),position=dict(x=0.,y=0.),colliders=[dict(id=456,damage_kind='enemy_tag')])
    def predict(*args):return [Hazard('p','e','EnemyMace',np.zeros((2,2)),np.ones((2,2)),np.ones(2,bool),'test',padding=.125)],None
    result,independent=pending_motion_history(enemy,times,o,current,predict,{'rotation'},'_enemyState')
    assert result is not None and not independent
    assert np.array_equal(result[1][456][1],np.full((2,2),1.125))
