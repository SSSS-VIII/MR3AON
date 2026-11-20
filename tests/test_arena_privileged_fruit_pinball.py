"""Native free fruit motion and authored rotating collider containment."""
import copy
import json
from pathlib import Path
import sys
import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts

CASES=json.loads((Path(__file__).parent/'fixtures/arena-privileged-fruit-pinball.json').read_text())['cases']


@pytest.mark.parametrize('case',CASES,ids=lambda c:str(c['frame']))
def test_native_free_fruit_root_and_rotating_capsule_are_enclosed(case):
    before,after=case['before'],case['after'];enemy=after['enemies'][0]
    assert before['state']['health']==after['state']['health']
    hazards,missing=hazard_forecasts(before,np.linspace(0,case['seconds'],61),PlayerModel(before))
    assert not missing and len(hazards)==1
    h=hazards[0];c=enemy['colliders'][0]
    xy=lambda v:np.array([v['x'],v['y']])
    assert np.linalg.norm(h.centers[-1]-xy(enemy['position']))<.001
    assert h.approximate and h.geometry=='sphere'
    # These original capsules are shorter than their scaled diameter. Verify
    # the actual sphere, not the nonphysical corners of its enclosing AABB.
    axis=('x','y','z')[c['direction']]
    radius=c['radius']*max(abs(c['scale'][a])for a in ('x','y','z')if a!=axis)
    assert c['height']*abs(c['scale'][axis])/2<radius
    assert np.linalg.norm(xy(c['center'])-h.centers[-1])+radius<=h.extents[-1,0]+.001


@pytest.mark.parametrize('variant',('hanging','nonidentity_parent','missing_geometry'))
def test_unmodelled_fruit_attachment_or_coordinate_space_is_not_silently_ignored(variant):
    before=copy.deepcopy(CASES[0]['before']);e=before['enemies'][0]
    if variant=='hanging':e['fields']['_enemyState']='hangonenemy: 0'
    elif variant=='nonidentity_parent':e['local_movement_parent_identity']=False
    else:e['colliders'][0].pop('rotation_envelope')
    hazards,missing=hazard_forecasts(before,np.linspace(0,.5,61),PlayerModel(before))
    assert not hazards and missing
