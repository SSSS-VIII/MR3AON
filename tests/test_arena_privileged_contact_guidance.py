"""A real local-window dead end contains a wider two-jump physical path."""
import json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_policy import InternalController,witness_operations,contact_guided_options
from arena_privileged_model import PlayerModel,hazard_forecasts,clearance

OBS=json.loads((Path(__file__).parent/'fixtures/arena-privileged-contact-guidance.json').read_text())['observation']


def test_real_static_blade_dead_end_retains_a_complete_independently_jittered_path():
    controller=InternalController();proposal=controller.decide(OBS)
    assert proposal.reason=='approach_center_of_native_safe_window'
    plan=controller.scheduled
    assert plan['action']=='jump'and plan['witness']['action']=='jump'
    assert proposal.window[1]-proposal.window[0]>=2*controller.timing_radius-1e-8
    model=PlayerModel(OBS);times=np.linspace(0.,1.8,217)
    hazards,missing=hazard_forecasts(OBS,times,model);assert not missing
    for first in (0.,-controller.timing_radius,controller.timing_radius):
        for second in (0.,-controller.timing_radius,controller.timing_radius):
            operations=witness_operations(model,times,(proposal.delay+first,plan['action']),plan['witness'],second)
            assert operations is not None
            body,motors,valid=model.trajectory(times,operations)
            assert valid and model.terrain_clearances(motors).min()>.025
            for hazard in hazards:
                shape=model.interaction_bodies(motors)if hazard.interaction else body
                assert clearance(shape,hazard).min()>.025


def test_inflated_geometry_is_a_proposal_heuristic_and_cannot_replace_endpoint_checks():
    model=PlayerModel(OBS);times=np.linspace(0.,1.8,217);hazards,missing=hazard_forecasts(OBS,times,model)
    assert not missing;calls=[];evidence={}
    def reject(*args):
        calls.append(args);return dict(full_horizon_safe=False)
    options=contact_guided_options(model,times,hazards,reject,lambda *args:True,.05,evidence)
    assert not options and calls and evidence['contact_guidance']['verified_full_candidates']>0


def test_moving_geometry_never_enters_the_static_contact_planner():
    from dataclasses import replace
    model=PlayerModel(OBS);times=np.linspace(0.,1.8,217);hazards,_=hazard_forecasts(OBS,times,model)
    moving=hazards[0].centers.copy();moving[-1,0]+=.01
    hazards=[replace(hazards[0],centers=moving),*hazards[1:]]
    def unexpected(*args):raise AssertionError('Dynamic geometry reached the static planner')
    assert contact_guided_options(model,times,hazards,unexpected,unexpected,.05,{})==[]
