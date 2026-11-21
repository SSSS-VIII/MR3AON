"""Original Euler ticks, root boxes, clock boundaries and activation lineage."""
from copy import deepcopy,copy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import mace_motion
from arena_privileged_model import PlayerModel,hazard_forecasts,rows
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-mace.json').read_text())


def test_native_fifty_ms_crosses_two_or_three_fixed_steps_without_continuous_rotation_bias():
    errors=[];checked=0
    for case in DATA['cases']:
        o=case['before'];times=np.unique(np.r_[0.,[q['seconds']for q in case['after']]])
        hs,missing=hazard_forecasts(o,times,PlayerModel(o));ids={e['id']for e in o['enemies']if e['type']=='EnemyMace'}
        assert not any(m['id']in ids for m in missing)
        for q in case['after']:
            i=int(np.searchsorted(times,q['seconds']));enemy=q['enemy']
            for h in (h for h in hs if h.enemy==enemy['id']):
                c=next(c for c in enemy['colliders']if c['id']==h.id)
                if not c['active']or not c['enabled']:continue
                point=np.array([c['center'][a]for a in('x','y')]);errors.append(np.linalg.norm(point-h.centers[i]))
                assert errors[-1]<.00005
                extent=np.array([c['extents'][a]for a in('x','y')])
                assert np.all(abs(point-h.centers[i])+extent<=h.extents[i]+h.padding+.0001)
                assert h.geometry=='obb'and h.quads is not None;checked+=1
    assert checked>20 and max(errors)<.00005


@pytest.mark.parametrize('change',['hook','callback','animation','script','child','body','interpolation','parent','reflection','clock','scale','nan'])
def test_unbound_geometry_or_clock_does_not_fall_back_to_continuous_rotation(change):
    o=deepcopy(DATA['cases'][0]['before']);enemy=next(e for e in o['enemies']if e['type']=='EnemyMace');g=enemy['mace_geometry']
    if change=='hook':g['native_motion']=False
    if change=='callback':g['callbacks_clear']=False
    if change=='animation':g['animated_tree']=True
    if change=='script':g['component_types'].append('UnknownMover')
    if change=='child':g['colliders'][0]['direct_root']=False
    if change=='body':g['physics']['gravity']=True
    if change=='interpolation':g['physics']['interpolation']='Interpolate: 1'
    if change=='parent':g['parent_axes']['x']['x']=2.
    if change=='reflection':g['parent_axes']['x']['x']=-1.
    if change=='clock':o['state']['time']+=1.
    if change=='scale':g['local_scale']['x']=0.
    if change=='nan':g['parent_axes']['z']['x']=float('nan')
    result,reason=mace_motion(enemy,np.linspace(0.,1.,121),o,PlayerModel(o))
    assert result is None and reason.startswith('mace_')


def test_zero_query_keeps_current_native_pose_and_halfway_clock_bounds_keep_whole_ticks():
    o=DATA['cases'][0]['before'];enemy=next(e for e in o['enemies']if e['type']=='EnemyMace');p=PlayerModel(o)
    age=o['state']['time']-enemy['fields']['_lastFixedUpdateTime'];boundary=p.tick-age
    times=np.array([0.,boundary,boundary+p.tick/2]);result,why=mace_motion(enemy,times,o,p)
    assert not why and result[1][0]==0.
    step=np.deg2rad(enemy['fields']['_speedRotate']*o['role']['data']['_moveSpeed']*.125*p.tick)
    assert abs(result[1][-1]-step)<.000001
    middle=result[1][1];error=result[5]['angular_error'][1]
    assert middle-error<=0<=middle+error and middle-error<=step<=middle+error


def test_counterfactual_without_real_pre_key_activation_lineage_is_rejected():
    o=DATA['cases'][0]['before'];enemy=next(e for e in o['enemies']if e['type']=='EnemyMace');p=PlayerModel(o)
    p.initial=copy(p.initial)
    assert mace_motion(enemy,np.linspace(0.,1.,121),o,p)[1]=='mace_past_activation_history_unbound'


def test_waiting_state_checks_role_activation_and_retains_one_tick_state_change_delay():
    o=deepcopy(DATA['cases'][0]['before']);enemy=next(e for e in o['enemies']if e['type']=='EnemyMace')
    enemy['fields']['_enemyState']='None: 1';enemy['custom']['_activateDistance']=1000.
    p=PlayerModel(o);times=np.linspace(0.,.3,37);result,why=mace_motion(enemy,times,o,p)
    assert not why
    # Even already within activation distance, None changes state at the
    # first future fixed tick; it does not rotate during that same tick.
    assert np.all(result[1][times<=p.tick-p.clock_age+1e-7]==0.)
    assert abs(result[1][-1])>0


def test_already_rotating_before_key_keeps_independent_native_lattice():
    case=DATA['cases'][0];o=case['before'];enemy=next(e for e in o['enemies']if e['type']=='EnemyMace')
    p=PlayerModel(o);times=np.linspace(0.,1.,121);_,motors,valid=p.trajectory(times);assert valid
    current=copy(p);current.initial=copy(p.initial)
    current._reference_history=dict(model=p,times=times,motors=motors,indices=np.arange(len(times)),offset=0.)
    a,why=mace_motion(enemy,times,o,p);b,why2=mace_motion(enemy,times,o,current)
    assert not why and not why2 and np.array_equal(a[1],b[1])
    changed=deepcopy(o);changed['role']['data']['_moveSpeed']+=1.
    assert mace_motion(enemy,times,changed,current)[1]=='mace_past_activation_history_unbound'


def test_waiting_activation_is_propagated_from_original_pre_key_world():
    origin=deepcopy(DATA['cases'][0]['before']);old=next(e for e in origin['enemies']if e['type']=='EnemyMace')
    old['fields']['_enemyState']='None: 1';old['custom']['_activateDistance']=1000.
    prior=PlayerModel(origin);enemy_age=origin['state']['time']-old['fields']['_lastFixedUpdateTime']
    elapsed=prior.tick-enemy_age+.00001;o=deepcopy(origin);o['state']['time']+=elapsed
    enemy=next(e for e in o['enemies']if e['id']==old['id']);enemy['fields']['_enemyState']='rotation: 0'
    enemy['fields']['_lastFixedUpdateTime']+=prior.tick
    times=np.linspace(0.,1.,121);query=elapsed+times;mesh=np.unique(np.r_[np.linspace(0.,query[-1],241),query])
    _,motors,valid=prior.trajectory(mesh);assert valid
    ix=np.searchsorted(mesh,query);current=PlayerModel(o);current.initial=copy(motors[ix[0]])
    current._reference_history=dict(model=prior,times=mesh,motors=motors,indices=ix,offset=elapsed)
    result,why=mace_motion(enemy,times,o,current)
    assert not why and 'actual pre-key world'in result[2]and result[5]['mace_shapes']
    h=result[5]['mace_shapes'][enemy['colliders'][0]['id']]
    assert h['geometry']=='obb'and h['quads'].shape==(len(times),4,2)
