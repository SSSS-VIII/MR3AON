"""Source reducers checked against saved original-client future states."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts,rows

CASES=json.loads((Path(__file__).parent/'fixtures/arena-privileged-families.json').read_text())


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['kind'])
def test_half_second_native_future_matches_source_reducer_or_authored_envelope(case):
    before,after=case['before'],case['after'];dt=case['seconds']
    assert .49<dt<.51
    times=np.linspace(0.,dt,61)
    forecasts,missing=hazard_forecasts(before,times,PlayerModel(before))
    if case['kind']in ('EnemyGhostFire','EnemyMace'):
        # Historical captures predate full hierarchy/native-clock binding.
        # Do not synthesize new read-only proof into the old observations.
        assert not forecasts and missing[0]['reason']==('ghost_original_geometry_missing'if case['kind']=='EnemyGhostFire'else'mace_original_geometry_missing')
        return
    assert not missing
    truth={c['id']:c for e in rows(after['enemies']) for c in rows(e['colliders'])}
    checked=0
    for h in forecasts:
        c=truth.get(h.id)
        if not c or not c['active'] or not c['enabled']:
            continue
        actual=np.array([c['center'][a] for a in ('x','y')])
        if case.get('conservative_timing_envelope'):
            assert h.approximate and h.padding>0
            extent=np.array([c['extents'][a] for a in ('x','y')])
            assert np.all(np.abs(h.centers[-1]-actual)+extent<=h.extents[-1]+h.padding+.001)
        elif case['kind']=='EnemyHideBlade' or case.get('conservative_envelope'):
            actual_extent=np.array([c['extents'][a] for a in ('x','y')])
            assert np.all(h.centers[-1]-h.extents[-1]<=actual-actual_extent+.001)
            assert np.all(h.centers[-1]+h.extents[-1]>=actual+actual_extent-.001)
            if case['kind']=='EnemyArrow':
                # AABB containment alone can conceal a wrong shaft angle.
                # Check every actual corner against all original box edges.
                outer=h.quads[-1];inner=np.array([[p['x'],p['y']]for p in c['quad']])
                edges=np.roll(outer,-1,axis=0)-outer
                signed_area=np.sum(outer[:,0]*np.roll(outer[:,1],-1)-
                                   outer[:,1]*np.roll(outer[:,0],-1))
                for origin,edge in zip(outer,edges):
                    relative=inner-origin
                    side=(edge[0]*relative[:,1]-edge[1]*relative[:,0])*np.sign(signed_area)
                    assert np.all(side>=-.0015*np.linalg.norm(edge))
        else:
            tolerance=.001 if case['kind']=='EnemyEliteDart' else .011
            assert np.linalg.norm(h.centers[-1]-actual)<tolerance
            if case['kind']=='EnemyPinball':
                extent=np.array([c['extents'][a] for a in ('x','y')])
                assert np.linalg.norm(h.extents[-1]-extent)<.0001
        checked+=1
    assert checked


def test_hidden_disabled_zero_scale_shape_has_future_danger_before_contact():
    case=next(c for c in CASES if c['kind']=='EnemyHideBlade');before=case['before']
    enemy=before['enemies'][0]
    assert not any(c['enabled'] for c in enemy['colliders'])
    assert max(c['extents']['y'] for c in enemy['colliders'])==0
    model=PlayerModel(before)
    hazards,missing=hazard_forecasts(before,np.linspace(0,1.8,217),model)
    assert not missing and hazards
    assert all(h.extents[:,1].max()>.5 for h in hazards)
    assert any(h.active[-1] for h in hazards)


def test_unknown_concrete_native_class_stays_explicit():
    before=json.loads(json.dumps(CASES[0]['before']))
    before['enemies'][0]['type']='EnemyNotYetModelled'
    hazards,missing=hazard_forecasts(before,np.linspace(0,1,121),PlayerModel(before))
    assert not hazards
    assert missing[0]['reason']=='motion_model_missing'
