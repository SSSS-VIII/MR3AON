"""Native spring geometry is avoidable using the actual pickup collider size."""
from dataclasses import replace
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts,clearance

OBS=json.loads((Path(__file__).parent/'fixtures/arena-privileged-spring.json').read_text())['observation']


def test_native_pickup_envelope_uses_capsule_axis_height_not_its_z_scale():
    model=PlayerModel(OBS)
    assert model.interaction_radius==pytest.approx(.65,abs=.0001)


def test_spring_does_not_block_the_entire_future_horizontal_corridor():
    model=PlayerModel(OBS)
    assert not any(s.startswith('item:ItemSpring') for s in model.unsupported)
    hazards,_=hazard_forecasts(OBS,np.array([0.,.1]),model)
    spring=next(h for h in hazards if h.kind=='ItemSpring')
    assert spring.interaction and spring.approximate
    assert 'PopBySpring remains unsupported' in spring.source
    # Counterfactual path next to an actual native trigger corner: the narrow
    # damage body misses while the original, larger pickup profile touches it.
    corner=min(spring.quads[0],key=lambda p:p[0])
    r=model.body_at(model.initial)[2]
    x=corner[0]-(r+.052+model.interaction_radius)/2
    m=replace(model.initial,x=x,y=corner[1],mode='runonground',
              offset_render=0.,collider_delay=0.)
    hurt=np.tile(model.body_at(m),(2,1))
    pickup=model.interaction_bodies([m,m])
    assert clearance(hurt,spring).min()>0
    assert clearance(pickup,spring).min()<0


def test_rotating_or_already_triggered_springs_stay_explicit_until_pop_is_modelled():
    for key in ('_needRotate','isTrigger'):
        obs=json.loads(json.dumps(OBS))
        item=next(i for i in obs['mechanism_items']if i['type']=='ItemSpring')
        item['fields'][key]=True
        model=PlayerModel(obs)
        assert 'item:ItemSpring' in model.unsupported
        assert not model.contact_avoidance
