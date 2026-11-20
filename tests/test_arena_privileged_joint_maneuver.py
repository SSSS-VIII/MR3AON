"""Multi-input model witnesses retain real native prefixes and independent X."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab'))
from arena_privileged_model import PlayerModel,hazard_forecasts,clearance
from arena_privileged_policy import InternalController,witness_operations
from privileged_search import select_alternative
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-joint-maneuver.json').read_text())


def test_two_key_rope_maneuver_has_complete_endpoint_model_witness_without_native_trials():
    o=DATA['observation'];c=InternalController(collect_alternatives=True);r=c.decide(o)
    assert r.reason=='approach_center_of_native_safe_window'
    assert c.scheduled['action']==c.scheduled['witness']['action']=='jump'
    assert r.evidence['selected']['full_horizon_safe']
    assert r.window[1]-r.window[0]>=.1-1e-8
    assert r.evidence['native_rollouts']==r.evidence['restores']==0
    assert all(v['full_horizon_safe']for v in r.evidence['window_choice']['endpoints'])


def test_next_input_is_anchored_independently_but_first_key_physical_history_is_retained():
    o=DATA['observation'];c=InternalController();c.decide(o)
    model=PlayerModel(o);times=np.linspace(0.,1.8,217);witness=c.scheduled['witness']
    a=witness_operations(model,times,(.05,'jump'),witness)
    b=witness_operations(model,times,(.15,'jump'),witness)
    assert a and b and a[1][0]==pytest.approx(b[1][0],abs=.003)
    _,early,valid_a=model.trajectory(times,a);_,late,valid_b=model.trajectory(times,b)
    assert valid_a and valid_b
    ix=np.searchsorted(times,.12)
    assert abs(early[ix].y-late[ix].y)>.1


def test_real_coast_prefix_keeps_earlier_counterfactual_and_complete_witness():
    c=InternalController();c.decide(DATA['observation']);due=c.scheduled['due']
    r=c.decide(DATA['after_coast'])
    assert r.reason=='approach_center_of_native_safe_window'
    assert c.scheduled['due']==due
    assert r.evidence['retained_early_endpoint']['result']['safe']
    assert all(len(ops)==2 for ops in c.scheduled['_negative_operations'])


def test_vm_alternative_keeps_and_revalidates_the_second_world_position():
    o=DATA['observation'];first=InternalController(collect_alternatives=True).decide(o)
    option=first.evidence['alternatives'][0];c=InternalController(collect_alternatives=True)
    select_alternative(c,option,o['state']['time']);target=c.scheduled['witness']['world_x']
    assert c.scheduled['witness']is not option['witness']
    r=c.decide(o)
    assert r.reason=='approach_selected_internal_window'
    assert c.scheduled['witness']['world_x']==target
    assert all(len(ops)==2 for ops in c.scheduled['_negative_operations'])


def test_known_native_local_reset_dead_end_is_rejected_before_delivering_down():
    o=json.loads((Path(__file__).parent/'fixtures/arena-privileged-local-reset-deadend.json').read_text())['observation']
    r=InternalController().decide(o)
    assert r.action!='down'
    assert any(v['action']=='down'for v in r.evidence['locally_safe_dead_ends'])


def test_local_continuation_retains_all_independent_model_endpoints():
    o=json.loads((Path(__file__).parent/'fixtures/arena-privileged-native.json').read_text())
    controller=InternalController();proposal=controller.decide(o)
    witness=controller.scheduled['witness'];model=PlayerModel(o);times=np.linspace(0.,1.8,217)
    # This first input alone cannot justify the whole horizon.
    body,motors,valid=model.trajectory(times,((proposal.delay,controller.scheduled['action']),))
    hs,missing=hazard_forecasts(o,times,model,motors)
    assert valid and not missing and any(np.min(clearance(body,h))<=.025 for h in hs)
    for first in (-controller.timing_radius,0.,controller.timing_radius):
        anchored=witness_operations(model,times,(proposal.delay+first,controller.scheduled['action']),witness)
        assert anchored and len(anchored)==2
        for second in (-controller.timing_radius,0.,controller.timing_radius):
            operations=(anchored[0],(anchored[1][0]+second,anchored[1][1]))
            body,motors,valid=model.trajectory(times,operations)
            hs,missing=hazard_forecasts(o,times,model,motors)
            assert valid and not missing
            assert np.min(model.terrain_clearances(motors))>.025
            assert all(np.min(clearance(body,h))>.025 for h in hs)
