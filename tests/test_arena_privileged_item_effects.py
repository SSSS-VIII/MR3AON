"""Keep original pickup effects visible after the source item disappears."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import coin_pile_marker,progression_marker,skill_issues
from arena_privileged_model import PlayerModel
from arena_privileged_policy import InternalController

FIXTURES=Path(__file__).parent/'fixtures'
SKILLS=json.loads((FIXTURES/'arena-privileged-active-skill.json').read_text())['skills']
PILES=json.loads((FIXTURES/'arena-privileged-coin-pile.json').read_text())['pending']


def test_native_consumed_water_ball_still_has_one_original_skill_and_ten_bullets():
    assert len(SKILLS['active'])==1 and len(SKILLS['bullets'])==10
    reasons=skill_issues(dict(skills=SKILLS))
    assert reasons==['active_skill:SkillWaterIcePiton','active_skill_bullet:SkillWaterIcePitonShooter']
    o=json.loads((FIXTURES/'arena-privileged-spring-launch.json').read_text())['cases'][0]['before']
    o['role']['skills']=SKILLS
    assert set(reasons)<=set(PlayerModel(o).unsupported)
    assert InternalController().decide(o).reason=='unsupported_native_mechanism'


def test_residual_bullets_cannot_disappear_with_the_finished_parent_skill():
    skills=deepcopy(SKILLS);skills['active']=[]
    assert skill_issues(dict(skills=skills))==['active_skill_bullet:SkillWaterIcePitonShooter']


def test_original_empty_lists_and_absent_move_skill_are_not_an_active_effect():
    assert skill_issues(dict(skills=dict(present=True,active={},bullets={})))==[]
    assert skill_issues(dict(skills=dict(present=False)))==['native_skill_manager_missing']


@pytest.mark.parametrize('entry',PILES,ids=lambda e:e['id'])
def test_original_pending_coin_pile_callbacks_only_classify_the_counter_transition(entry):
    expected='coin_pile_start'if entry['info']['_itemType']=='ItemCoinPileStart: 2'else'coin_pile_end'
    assert coin_pile_marker(entry)==expected
    item=dict(type='ItemCoinPileStart'if expected.endswith('start')else'ItemCoinPileEnd',
        info=entry['info'],custom=entry['custom'],fields=dict(_pickupRecycle=True))
    assert progression_marker(item)==expected


@pytest.mark.parametrize('change',['ball','unknown','omitted','wrong_class'])
def test_unknown_effects_do_not_inherit_a_coin_pile_counter_label(change):
    entry=deepcopy(PILES[0])
    if change=='ball':entry['info']['_itemType']='ItemElementBall: 5'
    if change=='unknown':entry['custom']['futureEffect']=True
    if change=='omitted':entry['custom_projection']['complete']=False
    if change=='wrong_class':entry['type']='ItemHorn'
    assert coin_pile_marker(entry)is None
