"""Native submerged/warning/rising water bamboo geometry, no route claims."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_families import curve_range

CASES=json.loads((Path(__file__).parent/'fixtures/arena-privileged-water-bamboo.json').read_text())


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['name'])
def test_original_full_rise_encloses_warning_and_later_damage_shapes(case):
    before=case['before']
    for target in case['targets']:
        times=np.array([0.,target['seconds']])
        hazards,missing=hazard_forecasts(before,times,PlayerModel(before))
        assert not missing and len(hazards)==1
        hazard=hazards[0]
        collider=next(c for c in target['enemy']['colliders']if c['id']==hazard.id)
        assert hazard.approximate and hazard.active.all()
        assert target['enemy']['info_identity']==before['enemies'][0]['info_identity']
        assert before['state']['health']==target['health']==5000
        # This is an envelope; its center intentionally differs from the
        # actual rising collider, including before it emerges from the floor.
        excess=np.abs([collider['center'][a]for a in ('x','y')]-hazard.centers[-1])+[collider['extents'][a]for a in ('x','y')]-hazard.extents[-1]
        assert max(excess)<1e-5


def test_unverified_water_variant_or_missing_authored_damage_geometry_is_rejected():
    observation=deepcopy(CASES[0]['before']);enemy=observation['enemies'][0]
    enemy['custom']['_render']=1
    hazards,missing=hazard_forecasts(observation,np.array([0.,.5]),PlayerModel(observation))
    assert not hazards and missing[0]['reason']=='water_bamboo_unverified_render_variant'
    enemy['custom']['_render']=0;enemy['position_tween']['from_colliders']=[]
    hazards,missing=hazard_forecasts(observation,np.array([0.,.5]),PlayerModel(observation))
    assert not hazards and missing[0]['reason']=='water_bamboo_unposed_damage_collider'


def test_curve_extrema_include_overshoot_between_equal_endpoint_values():
    keys=[dict(time=0.,value=0.,out_tangent=8.,in_tangent=0.,weighted_mode='None: 0'),
          dict(time=1.,value=0.,in_tangent=-8.,out_tangent=0.,weighted_mode='None: 0')]
    assert curve_range(keys)==pytest.approx((0.,2.))
    keys[0]['weighted_mode']='Out: 2'
    with pytest.raises(ValueError,match='weighted'):curve_range(keys)


def test_unknown_easing_and_custom_curve_wrap_are_explicitly_unsupported():
    observation=deepcopy(CASES[0]['before']);tween=observation['enemies'][0]['position_tween']
    tween['fields']['method']='easeInBack: 2'
    _,missing=hazard_forecasts(observation,np.array([0.,.5]),PlayerModel(observation))
    assert missing[0]['reason'].startswith('water_bamboo_easing:')
    tween['fields']['method']='custom: 0'
    tween['curve'][0].update(value=0.,out_tangent=8.)
    tween['curve'][1].update(value=0.,in_tangent=-8.)
    _,missing=hazard_forecasts(observation,np.array([0.,.5]),PlayerModel(observation))
    assert missing[0]['reason']=='water_bamboo_curve:curve_wrap_domain'
