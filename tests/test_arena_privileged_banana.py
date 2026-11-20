"""Original collectible callback must not become an invented hurt obstacle."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_policy import InternalController
from arena_privileged_families import collectible_kind

FIXTURE=json.loads((ROOT/'tests/fixtures/arena-privileged-banana.json').read_text())


@pytest.mark.parametrize('case',FIXTURE['cases'])
def test_original_zero_damage_banana_recycle_witnesses_remain_collectibles(case):
    before=case['before'];old=before['enemies'][0];after=case['after']
    assert before['state']['health']==after['state']['health']==5000
    assert not old['fields']['_dead'] and after['enemy']['fields']['_dead']
    assert old['info_identity']==after['enemy']['info_identity']
    assert collectible_kind(old)=='banana'
    hazards,missing=hazard_forecasts(before,np.linspace(0,1.8,217),PlayerModel(before))
    assert not missing
    assert all(h.enemy!=old['id']for h in hazards)
    # A nearby ordinary spider remains dangerous in the same native scene.
    if any(e['type']=='EnemySpider' for e in before['enemies']):
        assert any(h.kind=='EnemySpider'for h in hazards)


@pytest.mark.parametrize('changed',['attack','type','species'])
def test_altered_fruit_identity_or_damage_is_rejected(changed):
    observation=deepcopy(FIXTURE['cases'][0]['before']);observation['enemies']=observation['enemies'][:1]
    e=observation['enemies'][0]
    if changed=='attack':e['attack']=1
    if changed=='type':e['info']['_enemyType']='EnemyMoonCake: 1115'
    if changed=='species':e['fields']['_species']='Other: 0'
    assert collectible_kind(e)is None
    hazards,missing=hazard_forecasts(observation,np.linspace(0,1.8,217),PlayerModel(observation))
    assert not hazards and missing[0]['reason']=='unverified_fruit_identity_or_damage'


def test_known_banana_allows_coast_and_is_recorded_as_a_collectible():
    before=deepcopy(FIXTURE['cases'][0]['before']);before['enemies']=before['enemies'][:1]
    proposal=InternalController().decide(before)
    assert proposal.action=='none' and proposal.reason=='native_corridor_clear'
    assert proposal.evidence['collectibles'][0]['kind']=='banana'
    assert not proposal.evidence['unsupported_enemies']


def test_zero_attack_on_an_ordinary_spider_is_not_a_collectible_exemption():
    before=deepcopy(next(c['before']for c in FIXTURE['cases']if any(e['type']=='EnemySpider' for e in c['before']['enemies'])))
    spider=next(e for e in before['enemies']if e['type']=='EnemySpider');spider['attack']=0;before['enemies']=[spider]
    hazards,missing=hazard_forecasts(before,np.linspace(0,1.8,217),PlayerModel(before))
    assert collectible_kind(spider)is None and not missing
    assert hazards and hazards[0].kind=='EnemySpider'
