"""Cache only already bound static spawns; retain path-dependent guards."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_privileged_policy as policy

FIXTURES=Path(__file__).parent/'fixtures'
OBS=json.loads((FIXTURES/'arena-privileged-static-pickups.json').read_text())['observation']


def test_original_bound_static_blades_share_one_forecast_across_actor_candidates(monkeypatch):
    calls=[];original=policy.hazard_forecasts
    def counted(*args,**kwargs):
        calls.append(1);return original(*args,**kwargs)
    monkeypatch.setattr(policy,'hazard_forecasts',counted)
    proposal=policy.InternalController().decide(OBS)
    assert not proposal.evidence['coupled_forecasts']
    assert len(calls)==1 and proposal.evidence['evaluated']>0


def test_unbound_distant_static_prefab_can_become_imminent_on_another_actor_path():
    o=deepcopy(OBS)
    for e in o['pending_enemies']:e['block_start']['x']+=1000.
    for template in o['spawn_templates']['blades'].values():template['missing']=True
    result=policy.InternalController().decide(o)
    assert result.evidence['coupled_forecasts']


def test_original_pending_sword_keeps_actor_reference_recomputation():
    o=json.loads((FIXTURES/'arena-privileged-pending-sword.json').read_text())['cases'][0]['before']
    assert policy.InternalController().decide(o).evidence['coupled_forecasts']


def test_nontracking_bamboo_still_checks_candidate_spring_camera_branch(monkeypatch):
    o=deepcopy(OBS);o['pending_enemies']=[]
    o['enemies']=[dict(id=1,type='EnemyFlyBamboo',colliders=[],custom=dict(_followNinja=False),
                       fields=dict(_dead=False,_isRecycled=False))]
    def camera_contract(observation,times,player,trajectory_states=None,**kwargs):
        if trajectory_states is not None and any(m.mode in ('popup','popfall')for m in trajectory_states):
            return [],[dict(id=1,type='EnemyFlyBamboo',reason='spring_pop_camera_transition_not_validated')]
        return [],[]
    monkeypatch.setattr(policy,'hazard_forecasts',camera_contract)
    result=policy.InternalController().decide(o)
    assert result.evidence['coupled_forecasts']
    assert result.reason!='native_corridor_clear'
    assert not result.evidence['coast']['safe']
