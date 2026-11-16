"""A later action opportunity must agree with the measured controller cycle."""
from pathlib import Path
from copy import deepcopy
import dataclasses
import json
import math
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_action_timing import DecisionCadence
from arena_vision import Box,Track
from arena_bamboo_motion import BambooForecast
from arena_mpc import MpcAvoider


def replay_state():
    raw=json.loads((Path(__file__).parent/'fixtures/arena-measured-control-cycle.json').read_text())
    obs=raw['observation'];obs['player']=Box(**obs['player'])
    tracks=[]
    for item in obs['tracks']:
        item['box']=Box(**item['box'])
        kind=BambooForecast if item['kind']=='bamboo_forecast'else Track
        known={f.name for f in dataclasses.fields(kind)}
        track=kind(**{k:v for k,v in item.items()if k in known})
        for k,v in item.items():
            if k not in known:setattr(track,k,v)
        tracks.append(track)
    obs['tracks']=tracks
    cadence=DecisionCadence()
    for stamp in raw['history']:interval=cadence.observe(stamp)
    obs['decision_interval_seconds']=interval
    return obs


def policy(enabled):
    p=MpcAvoider();p.ground_static_search=True;p.ground_reserve_recovery=True
    p.ordinary_air_down_gap=.04;p.measured_control_step=enabled
    return p


def test_recorded_wait_depends_on_an_earlier_next_input_opportunity():
    obs=replay_state();before=deepcopy(obs)
    assert .08<obs['decision_interval_seconds']<.1
    assert policy(False).choose(obs)==(None,'mpc_wait')
    assert policy(True).choose(obs)==('jump','mpc_rope_up')
    assert obs==before


def test_disabled_mode_is_unaffected_by_cadence_or_invalid_unused_metadata():
    obs=replay_state();p=policy(False)
    for interval in [0.,.01,.15,math.nan]:
        obs['decision_interval_seconds']=interval
        assert p.control_step(obs)==.08
        assert p.choose(obs)==(None,'mpc_wait')


def test_fast_loop_retains_original_search_step_and_decision():
    obs=replay_state();obs['decision_interval_seconds']=.03
    assert policy(True).control_step(obs)==.08
    assert policy(True).choose(obs)==policy(False).choose(obs)


def test_search_geometry_uses_measured_time_and_leaves_class_default_unchanged():
    p=policy(True)
    assert p.control_step({'decision_interval_seconds':.112})==.112
    assert p.control_step({})==.08
    assert p.STEP==MpcAvoider.STEP==.08


@pytest.mark.parametrize('value',[True,-.1,math.nan,math.inf])
def test_invalid_enabled_interval_is_rejected(value):
    with pytest.raises(ValueError):policy(True).control_step({'decision_interval_seconds':value})


def test_cadence_uses_previous_intervals_with_a_bounded_window():
    c=DecisionCadence()
    assert [c.observe(t)for t in [1.,1.02,1.04]]==[0.,0.,0.]
    assert c.observe(1.06)==pytest.approx(.02)
    # One old cold delay must not permanently slow subsequent planning.
    c.observe(1.56)
    for i in range(1,41):result=c.observe(1.56+i*.09)
    assert len(c.intervals)==32
    assert result==pytest.approx(.09)


@pytest.mark.parametrize('value',[True,math.nan,math.inf,0.,-.1])
def test_bad_clock_does_not_corrupt_last_good_timestamp(value):
    c=DecisionCadence();c.observe(1.)
    with pytest.raises(ValueError):c.observe(value)
    assert c.previous==1.
    assert c.observe(1.1)==0.
