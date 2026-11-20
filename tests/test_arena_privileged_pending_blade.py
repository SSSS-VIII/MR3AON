"""Original static blades are bounded even before the terrain is instantiated."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_policy import InternalController

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-pending-blade.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_native_unborn_floor_ceiling_and_uninstantiated_blade_boxes(case):
    o=case['before'];q=case['after'];original=deepcopy(o)
    dt=q['state']['time']-o['state']['time'];times=np.linspace(0,dt,round(dt*120)+1)
    hs,missing=hazard_forecasts(o,times,PlayerModel(o));entry=o['pending_enemies'][0]
    forecasts=[h for h in hs if h.enemy==entry['id']]
    assert not missing and len(forecasts)==1 and o==original
    h=forecasts[0];box=next(c for c in q['enemy']['colliders']if c.get('damage_kind'))
    center=np.array([box['center'][a]for a in ('x','y')]);extent=np.array([box['extents'][a]for a in ('x','y')])
    assert np.all(abs(center-h.centers[-1])+extent<=h.extents[-1]+.0001)
    assert h.active.all()and h.approximate and 'unhit static box'in h.source
    assert entry['info_identity']==q['enemy']['info_identity']


def test_uninstantiated_static_blade_does_not_need_a_guessed_birth_or_vertical_gate():
    o=deepcopy(DATA['cases'][0]['before']);o['pending_enemies'][0]['vertical_gate']=True
    hs,missing=hazard_forecasts(o,np.linspace(0,.1,13),PlayerModel(o))
    hs=[h for h in hs if h.enemy==o['pending_enemies'][0]['id']]
    assert not missing and len(hs)==1 and hs[0].active.all()


@pytest.mark.parametrize('change,reason',[
    ('template','pending_blade_original_prefab_missing'),
    ('animated','pending_blade_original_static_box_binding'),
    ('hidden','pending_blade_original_static_box_binding'),
    ('render','pending_blade_render_variant'),
    ('rotation','pending_blade_native_rotation'),
    ('source','pending_blade_spawn_source'),
])
def test_unknown_prefab_motion_and_rotation_cannot_be_certified(change,reason):
    o=deepcopy(DATA['cases'][1]['before']);entry=o['pending_enemies'][0];template=o['spawn_templates']['blades']['EnemyBlade']
    if change=='template':template['missing']=True
    if change=='animated':template['colliders'][0]['static_chain']=False
    if change=='hidden':template['colliders'][0]['local_active']=False
    if change=='render':entry['custom']['_render']=2
    if change=='rotation':entry['pose_rotation']['w']=2.
    if change=='source':entry['source']='preLoadEnemyList'
    hs,missing=hazard_forecasts(o,np.linspace(0,1.8,217),PlayerModel(o))
    assert not hs and missing==[dict(id=entry['id'],type='EnemyBlade',reason=reason)]
    assert InternalController().decide(o).reason=='unsupported_native_mechanism'
