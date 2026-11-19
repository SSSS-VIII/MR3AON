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
    assert not missing
    truth={c['id']:c for e in rows(after['enemies']) for c in rows(e['colliders'])}
    checked=0
    for h in forecasts:
        c=truth.get(h.id)
        if not c or not c['active'] or not c['enabled']:
            continue
        actual=np.array([c['center'][a] for a in ('x','y')])
        if case['kind']=='EnemyHideBlade':
            actual_extent=np.array([c['extents'][a] for a in ('x','y')])
            assert np.all(h.centers[-1]-h.extents[-1]<=actual-actual_extent+.001)
            assert np.all(h.centers[-1]+h.extents[-1]>=actual+actual_extent-.001)
        else:
            assert np.linalg.norm(h.centers[-1]-actual)<.011
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
