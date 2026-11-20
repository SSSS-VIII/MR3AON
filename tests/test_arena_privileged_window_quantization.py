"""Real -40ms request becomes -50ms and exposes a previously accepted jump."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'tools/arena_checkpoint_lab'))
from arena_privileged_model import PlayerModel,hazard_forecasts,clearance
from arena_privileged_policy import InternalController
from privileged_search import select_alternative

CASE=json.loads((ROOT/'tests/fixtures/arena-privileged-window-quantization.json').read_text())


def test_original_counterexample_is_predicted_at_the_actual_quantized_endpoint():
    before=CASE['forecast_before'];failure=CASE['failure'];actual=failure['actual']
    operation=failure['actions'][1];nominal=operation['nominal_crossing_time']-before['state']['time']
    elapsed=actual['time']-before['state']['time']
    times=np.unique(np.r_[np.linspace(0,1.8,217),elapsed])
    model=PlayerModel(before);hazards,missing=hazard_forecasts(before,times,model)
    assert not missing
    assert operation['requested_shift_ms']==-40
    assert operation['actual_shift_ms']==pytest.approx(-50,abs=.01)
    assert actual['health']==4750 and failure['before']['health']==5000
    margins={}
    for radius in (.04,.05):
        body,motors,valid=model.trajectory(times,((nominal-radius,'jump'),))
        assert valid
        margins[radius]=min(clearance(body,h).min()for h in hazards)
        if radius==.05:
            at=int(np.searchsorted(times,elapsed));m=motors[at]
            assert np.linalg.norm([m.x-actual['position']['x'],m.y-actual['position']['y']])<.0002
    assert margins[.04]>.025
    assert margins[.05]<0


def test_latched_window_keeps_its_safety_deadline_when_new_native_traps_appear():
    controller=InternalController(collect_alternatives=True)
    first=controller.decide(CASE['origin']);stamp=CASE['origin']['state']['time']
    assert controller.requested_timing_radius==.04 and controller.timing_radius==.05
    delay=CASE['scheduled']['due']-stamp
    option=min(first.evidence['alternatives'],key=lambda o:abs(o['delay']-delay))
    select_alternative(controller,option,stamp)
    assert controller.scheduled['checked_until']==pytest.approx(stamp+controller.horizon)
    rejected=controller.decide(CASE['new_observation'])
    assert rejected.reason=='selected_internal_window_invalidated' and rejected.action=='none'
    evidence=rejected.evidence['pending_rejection']
    assert not evidence['checks'][0]['safe'] and evidence['checks'][1]['safe']
    assert evidence['checks'][0]['required_safe_until_seconds']>1.6
    assert evidence['visibility_changed']
    # Rejection occurs while the earlier endpoint is still in the future;
    # no injury, native branch trial or rollback was needed to discover it.
    assert CASE['new_observation']['state']['time']<CASE['scheduled']['due']-.05
    assert rejected.evidence['native_rollouts']==rejected.evidence['restores']==0


def test_original_sender_repeat_gap_covers_both_independent_endpoint_shifts():
    sample=CASE['repeat'];controller=InternalController(collect_alternatives=True)
    controller.delivered('jump',sample['previous_stamp'])
    proposal=controller.decide(sample['before']);stamp=sample['before']['state']['time']
    jumps=[o for o in proposal.evidence.get('alternatives',[])if o['action']=='jump']
    assert jumps
    for option in jumps:
        earliest=stamp+option['delay']-controller.timing_radius
        previous_latest=sample['previous_stamp']+controller.timing_radius
        assert earliest-previous_latest>=.1-.00002


def test_pending_key_is_not_sent_one_render_frame_before_its_checked_center():
    pair=json.loads((ROOT/'tests/fixtures/arena-privileged-pending.json').read_text())
    # Isolate scheduler timing on the real coasting role/support pair. The
    # original hazards are covered separately by the native counterexample.
    for observation in pair.values():observation['enemies']=[]
    before=pair['now'];stamp=before['state']['time'];controller=InternalController()
    controller.scheduled=dict(action='jump',due=stamp+1/60,window=(stamp-.05,stamp+.2),
                              origin_stamp=stamp-.1,checked_offsets_ms=[-50,50])
    controller.decide(pair['before'])
    proposal=controller.decide(before)
    assert proposal.action=='none' and proposal.delay==pytest.approx(1/60)
    assert controller.scheduled['due']>stamp


def test_new_object_after_the_early_endpoint_invalidates_the_old_proof():
    pair=json.loads((ROOT/'tests/fixtures/arena-privileged-pending.json').read_text())
    before=pair['now'];stamp=before['state']['time'];controller=InternalController()
    controller.scheduled=dict(action='jump',due=stamp,window=(stamp-.1,stamp+.1),
        origin_stamp=stamp-.1,checked_offsets_ms=[-50,50],negative_signature=[],search_choice=True)
    proposal=controller.decide(before)
    assert proposal.reason=='selected_internal_window_invalidated'
    assert proposal.action=='none' and proposal.evidence['pending_rejection']['visibility_changed']


def test_expired_search_window_is_not_recentered_as_a_fresh_action():
    pair=json.loads((ROOT/'tests/fixtures/arena-privileged-pending.json').read_text())
    before=pair['now'];stamp=before['state']['time'];controller=InternalController()
    controller.scheduled=dict(action='jump',due=stamp-.1,window=(stamp-.2,stamp+.1),
                              origin_stamp=stamp-.3,search_choice=True)
    proposal=controller.decide(before)
    assert proposal.reason=='selected_internal_window_invalidated'
    assert proposal.action=='none' and controller.scheduled is None


def introduced_blade(observation,x,y):
    return dict(id=987654,type='EnemyBlade',name='test_new_instance',info_identity=876543,
        position=dict(x=x,y=y,z=0),scale=dict(x=1,y=1,z=1),custom={},
        fields=dict(_dead=False,_isRecycled=False,m_index=765432),
        colliders=[dict(id=654321,name='hurt',type='SphereCollider',radius=.02,
            center=dict(x=x,y=y,z=0),extents=dict(x=.02,y=.02,z=.02),
            active=True,enabled=True,damage_kind='enemy_callback',depth_tilt=False)])


def test_new_distant_instance_rechecks_the_actual_earlier_trajectory_without_rollback():
    from dataclasses import asdict
    from arena_privileged_runner import json_safe
    pair=json.loads((ROOT/'tests/fixtures/arena-privileged-pending.json').read_text())
    controller=InternalController();controller.decide(pair['before'])
    now=pair['now'];now['enemies'].append(introduced_blade(now,now['state']['position']['x']+60,0))
    result=controller.decide(now)
    assert result.action=='jump'
    proof=result.evidence['retained_early_endpoint']
    assert proof['visibility_changed'] and proof['result']['safe']
    assert proof['seconds_since_origin']==pytest.approx(.05,abs=.00001)
    assert result.evidence['native_rollouts']==result.evidence['restores']==0
    # Frozen Python models stay in the policy/VM branch state, never leak
    # into the recorded proposal or its public JSON evidence.
    json.dumps(json_safe(asdict(result)),allow_nan=False)


def test_new_danger_after_the_early_key_is_checked_against_its_retained_jump():
    pair=json.loads((ROOT/'tests/fixtures/arena-privileged-pending.json').read_text())
    controller=InternalController();controller.decide(pair['before'])
    origin=pair['before']['state']['time'];now=pair['now'];elapsed=now['state']['time']-origin
    old=PlayerModel(pair['before']);times=np.linspace(0,elapsed+.1,37)
    body,_,valid=old.trajectory(times,((0.,'jump'),));assert valid
    x,y,radius,core=body[-1]
    now['enemies'].append(introduced_blade(now,float(x),float(y+radius+core+.01)))
    controller.scheduled['search_choice']=True
    result=controller.decide(now)
    assert result.action=='none' and result.reason=='selected_internal_window_invalidated'
    checks=result.evidence['pending_rejection']
    assert checks['nominal']['safe'] and checks['late']['safe']
    assert not checks['early']['safe']


def test_retained_endpoint_is_rejected_if_the_native_coast_prefix_changed():
    pair=json.loads((ROOT/'tests/fixtures/arena-privileged-pending.json').read_text())
    controller=InternalController();controller.decide(pair['before'])
    controller.scheduled['search_choice']=True
    pair['now']['state']['position']['x']+=1
    result=controller.decide(pair['now'])
    assert result.action=='none' and result.reason=='selected_internal_window_invalidated'
    assert result.evidence['pending_rejection']['early']['reason']=='unchanged_prefix_disagrees_with_native_state'
