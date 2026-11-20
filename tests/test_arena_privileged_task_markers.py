"""Source task markers are progress events; task success stays a separate goal."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from arena_privileged_families import progression_marker
from arena_privileged_model import PlayerModel
from arena_privileged_policy import InternalController

CASE=json.loads((ROOT/'tests/fixtures/arena-privileged-task-markers.json').read_text())


def test_original_task_end_boundary_is_not_an_unmodelled_motion_hazard():
    before=CASE['before'];after=CASE['after']
    assert before['state']['health']==after['state']['health']==5000
    assert not after['role']['mounted'] and not after['role']['god']
    assert before['special_task']['active'] and after['special_task']['observed']
    assert not after['special_task']['active']
    task=before['special_task']['fields']
    assert task['_currGoalValue']==52 and task['_goalValue']==125
    marker=before['mechanism_items'][0]
    assert progression_marker(marker)=='special_task_end'
    assert not PlayerModel(before).unsupported
    proposal=InternalController().decide(before)
    assert proposal.reason!='unsupported_native_mechanism'
    assert proposal.evidence['progression_markers'][0]['kind']=='special_task_end'
    # Carry the actual unfinished goal, never infer task success from motion.
    assert proposal.evidence['special_task']['fields']['_currGoalValue']==52


@pytest.mark.parametrize('changed',['identity','repeat','class','render'])
def test_unverified_marker_variants_remain_unsupported(changed):
    before=deepcopy(CASE['before']);marker=before['mechanism_items'][0]
    if changed=='identity':marker['info']['_itemType']='ItemUnknown: 999'
    if changed=='repeat':marker['fields']['_pickupRecycle']=False
    if changed=='class':marker['type']='ItemEvent'
    if changed=='render':marker['custom']['_render']=1
    assert progression_marker(marker)is None
    assert 'item:'+marker['type']in PlayerModel(before).unsupported


def test_original_start_counter_event_has_its_own_identity_binding():
    marker=deepcopy(CASE['before']['mechanism_items'][0])
    marker['type']='ItemSpecialTaskStart';marker['info']['_itemType']='ItemSpecialTaskStart: 43'
    assert progression_marker(marker)=='special_task_start'
