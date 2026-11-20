"""Original moving generator, complete pending queue and future native lasers."""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_families import alarm_shooter,alarm_shooter_path,planar_arc_bounds,planar_arc_cloud
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-alarm-shooter.json').read_text())

@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_native_movein_attack_leave_and_overshot_local_field(case):
    o=case['before'];e=o['enemies'][0];q=case['after']['enemy']
    dt=case['after']['state']['time']-o['state']['time'];times=np.linspace(0.,dt,round(dt*120)+1)
    original=deepcopy(o);hs,missing=hazard_forecasts(o,times,PlayerModel(o))
    assert not missing and o==original
    h=next(h for h in hs if h.kind=='EnemyAlarmShooter');c=q['colliders'][0]
    actual=np.array([c['center'][a]for a in ('x','y')]);extent=np.array([c['extents'][a]for a in ('x','y')])
    assert np.all(abs(actual-h.centers[-1])+extent<=h.extents[-1])
    assert not o['role']['mounted']and not o['role']['god']
    if case['name']=='native_overshoot_field_after_transform_snap':
        assert e['fields']['_localPos']['x']>5
        assert q['fields']['_localPos']['x']<4.81
        assert q['fields']['_state']=='Attack: 2'


def test_all_new_native_beams_are_covered_before_they_exist():
    case=DATA['future'];o=case['before'];new=case['after']['new_lasers']
    dt=case['after']['state']['time']-o['state']['time'];times=np.linspace(0.,dt,round(dt*120)+1)
    hs,missing=hazard_forecasts(o,times,PlayerModel(o));generated=[h for h in hs if isinstance(h.id,str)and h.id.startswith('spawn:')]
    assert not missing and len(new)==8 and generated
    prior={(e['id'],e['info_identity'],e['fields']['m_index'])for e in o['enemies']}
    for e in new:
        assert(e['id'],e['info_identity'],e['fields']['m_index'])not in prior
        c=e['colliders'][0];actual=np.array([c['center'][a]for a in ('x','y')]);extent=np.array([c['extents'][a]for a in ('x','y')])
        assert any(h.active[-1]and np.all(abs(actual-h.centers[-1])+extent<=h.extents[-1])for h in generated)
        assert e['scale']['x']==1 # original zero parameter fallback to One


def test_original_timer_stays_accumulated_after_first_bullet():
    o=deepcopy(DATA['cases'][1]['before']);e=o['enemies'][0];f=e['fields']
    f.update(_state='Attack: 2',_bulletIndex=0,_shootTimer=0,_beforeShootTime=0)
    o['state']['time']=f['_lastFixedUpdateTime']
    path,reason=alarm_shooter_path(e,np.linspace(0.,.2,25),o,PlayerModel(o))
    assert not reason
    assert [s['tick']for s in path['shots']]==[6,7]
    assert path['shots'][1]['seconds']-path['shots'][0]['seconds']==pytest.approx(.02)


@pytest.mark.parametrize('change,reason',[
 ('truncated','alarm_shooter_complete_pending_bullets'),
 ('index','alarm_shooter_complete_pending_bullets'),
 ('phase','alarm_shooter_native_phase_or_direction'),
 ('parent','alarm_shooter_original_planar_parent'),
 ('clock','alarm_shooter_original_reference_clock'),
 ('parameter','alarm_shooter_native_parameter_domain'),
 ('callback','alarm_shooter_original_device_sphere'),
 ('animation','alarm_shooter_unverified_damage_transform_chain'),
])
def test_unknown_generator_state_is_not_reduced_to_its_visible_body(change,reason):
    o=deepcopy(DATA['cases'][0]['before']);e=o['enemies'][0]
    if change=='truncated':e['alarm_shooter']['truncated']=True
    if change=='index':e['fields']['_bulletIndex']=999
    if change=='phase':e['fields']['_state']='Unknown: 99'
    if change=='parent':e['bullet_geometry']['parent_axes_identity']=False
    if change=='clock':e['fields']['_lastFixedUpdateTime']-=1
    if change=='parameter':e['fields']['_shootMoveSpeed']=float('nan')
    if change=='callback':e['colliders'][0]['damage_owner']=0
    if change=='animation':e['bullet_geometry']['chains'][0]['nodes'][0]['scripts'].append('UnityEngine.Animator')
    result,missing=alarm_shooter(e,np.array([0.,.5]),o,PlayerModel(o))
    assert result is None and missing==reason


@pytest.mark.parametrize('lower,upper',[(-1.,.6),(6.,6.02),(-10.,14.)])
def test_batched_continuous_angle_extrema_equal_scalar_source_geometry(lower,upper):
    points=np.random.default_rng(217).normal(size=(8,6,2))
    lo,hi=planar_arc_cloud(points,lower,upper)
    for i,cloud in enumerate(points):
        expected=[planar_arc_bounds(p,lower,upper)for p in cloud]
        np.testing.assert_allclose(lo[i],np.min([v[0]for v in expected],axis=0),atol=1e-12)
        np.testing.assert_allclose(hi[i],np.max([v[1]for v in expected],axis=0),atol=1e-12)


def test_future_targeted_shot_uses_candidate_actor_path_at_birth():
    o=deepcopy(DATA['cases'][1]['before']);e=o['enemies'][0]
    e['fields'].update(_state='Attack: 2',_bulletIndex=0,_shootTimer=0,_beforeShootTime=.3)
    for p in e['alarm_shooter']['bullets']:p['_pointToNinja']=True
    model=PlayerModel(o);times=np.linspace(0.,.8,97)
    _,coast,coast_valid=model.trajectory(times)
    _,jump,jump_valid=model.trajectory(times,((0.,'jump'),))
    assert coast_valid and jump_valid
    a,reason=alarm_shooter(e,times,o,model,coast);b,other=alarm_shooter(e,times,o,model,jump)
    assert not reason and not other
    assert len(a[5]['generated_hazards'])==len(b[5]['generated_hazards'])==2
    assert abs(a[5]['generated_hazards'][0].centers[-1,1]-b[5]['generated_hazards'][0].centers[-1,1])>.1


def test_horizontal_forecast_memo_matches_uncached_world_across_candidate_actions():
    o=DATA['future']['before'];model=PlayerModel(o);times=np.linspace(0.,1.,121);memo={}
    for operations in [(),((.1,'jump'),),((.1,'down'),),((.1,'jump'),(.4,'down'))]:
        _,states,_=model.trajectory(times,operations)
        actual,missing=hazard_forecasts(o,times,model,states,forecast_cache=memo)
        expected,unmapped=hazard_forecasts(o,times,model,states)
        assert missing==unmapped
        assert [h.id for h in actual]==[h.id for h in expected]
        for a,b in zip(actual,expected):
            np.testing.assert_array_equal(a.centers,b.centers)
            np.testing.assert_array_equal(a.extents,b.extents)
            np.testing.assert_array_equal(a.active,b.active)


def test_tracking_birth_is_not_reused_from_a_different_vertical_candidate():
    o=deepcopy(DATA['cases'][1]['before']);e=o['enemies'][0]
    e['fields'].update(_state='Attack: 2',_bulletIndex=0,_shootTimer=0,_beforeShootTime=.3)
    for p in e['alarm_shooter']['bullets']:p['_pointToNinja']=True
    model=PlayerModel(o);times=np.linspace(0.,.8,97);memo={};forecasts=[]
    for operations in [(),((0.,'jump'),)]:
        _,states,_=model.trajectory(times,operations)
        actual,missing=hazard_forecasts(o,times,model,states,forecast_cache=memo)
        expected,unmapped=hazard_forecasts(o,times,model,states)
        assert not missing and not unmapped
        for a,b in zip(actual,expected):np.testing.assert_array_equal(a.centers,b.centers)
        forecasts.append(next(h for h in actual if isinstance(h.id,str)))
    assert abs(forecasts[0].centers[-1,1]-forecasts[1].centers[-1,1])>.1
