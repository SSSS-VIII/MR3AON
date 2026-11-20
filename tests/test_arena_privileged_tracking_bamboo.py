"""Original aim tracking stops at lock; physical roots are not render roots."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_families import tracking_bamboo

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-tracking-bamboo.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_original_y_lerp_lock_and_flight_attack_contains_native_box(case):
    o=case['before'];original=deepcopy(o);q=case['after'];e=o['enemies'][0]
    dt=q['state']['time']-o['state']['time'];times=np.linspace(0,dt,round(dt*120)+1)
    model=PlayerModel(o);_,motors,valid=model.trajectory(times,case['operations'])
    assert valid
    hs,missing=hazard_forecasts(o,times,model,motors)
    assert not missing and len(hs)==1 and original==o
    h=hs[0];c=next(v for v in q['enemy']['colliders']if v['id']==h.id)
    assert h.geometry=='aabb'and h.approximate
    assert not c['active']or h.active[-1]
    if not e['fields']['_enemyState'].startswith('none:'):
        # X before attack activation is intentionally unspecified. The
        # tracked Y is checked even while the original attack is inactive.
        over=abs(np.array([c['center'][a]for a in ('x','y')])-h.centers[-1])+np.array([c['extents'][a]for a in ('x','y')])-h.extents[-1]
        assert over[1]<=1e-6
        if c['active']:assert max(over)<=1e-6
    assert not o['role']['mounted']and not o['role']['god']


def test_aim_uses_each_candidate_physical_y_but_lock_freezes_it():
    times=np.linspace(0.,1.8,217)
    for name in ('aim_with_original_jump_down','locked_to_flight'):
        o=next(c['before']for c in DATA['cases']if c['name']==name);e=o['enemies'][0];model=PlayerModel(o)
        _,motors,valid=model.trajectory(times);assert valid
        raised=[replace(m,physical_y=m.physical_y+6.,previous_y=m.previous_y+6.)if i else m for i,m in enumerate(motors)]
        a,reason=tracking_bamboo(e,times,o,model,motors);assert not reason
        b,reason=tracking_bamboo(e,times,o,model,raised);assert not reason
        ay=a[4][next(iter(a[4]))][0][:,1];by=b[4][next(iter(b[4]))][0][:,1]
        if name.startswith('aim'):assert max(abs(ay-by))>1.
        else:assert np.array_equal(ay,by)


def test_none_has_no_attack_before_complete_native_warning_but_long_future_is_not_ignored():
    o=DATA['cases'][0]['before'];e=o['enemies'][0];model=PlayerModel(o)
    a,reason=tracking_bamboo(e,np.array([0.,1.8]),o,model)
    assert not reason and not any(a[3])
    a,reason=tracking_bamboo(e,np.array([0.,4.]),o,model)
    assert a is None and reason=='tracking_bamboo_future_camera_activation'


@pytest.mark.parametrize('change,reason',[
    ('split','tracking_bamboo_original_unsplit_instance'),
    ('reverse','tracking_bamboo_unverified_run_direction'),
    ('shape','tracking_bamboo_original_selected_attack_box'),
    ('clock','tracking_bamboo_original_fixed_clock'),
    ('phase','tracking_bamboo_unmapped_phase:unknown'),
    ('speed','tracking_bamboo_native_parameter_domain'),
    ('camera','tracking_bamboo_changing_camera_projection'),
])
def test_unknown_target_or_projection_cannot_become_a_frozen_safe_projectile(change,reason):
    o=deepcopy(next(c['before']for c in DATA['cases']if c['name']=='ready_to_flight'));e=o['enemies'][0]
    if change=='split':e['fields']['_fissonState']=True
    if change=='reverse':o['camera']['direction']=-1
    if change=='shape':next(c for c in e['colliders']if c['name']=='Attack'and c['parent_active'])['depth_tilt']=True
    if change=='clock':e['fields']['_lastFixedUpdateTime']-=1
    if change=='phase':e['fields']['_enemyState']='unknown: 7'
    if change=='speed':e['fields']['_flySpeed']=float('nan')
    if change=='camera':o['camera']['fields']['_fieldViewChangeSpeed']=1.
    a,missing=tracking_bamboo(e,np.linspace(0.,1.,121),o,PlayerModel(o))
    assert a is None and missing==reason
