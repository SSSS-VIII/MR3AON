"""A visible new physical circle must be available to the candidate planner."""
from copy import deepcopy
from dataclasses import fields
import json
from pathlib import Path

from arena_bamboo_motion import BambooForecast
from arena_mpc import MpcAvoider
from arena_policy import Avoider
from arena_vision import Box, Track


def fixture_state():
    saved=json.loads((Path(__file__).parent/'fixtures/arena-young-sphere-decision.json').read_text())
    obs=saved['observation']
    obs['player']=Box(**obs['player'])
    tracks=[]
    for raw in obs['tracks']:
        cls=BambooForecast if raw['kind']=='bamboo_forecast' else Track
        raw['box']=Box(**raw['box'])
        tracks.append(cls(**{k:v for k,v in raw.items() if k in {f.name for f in fields(cls)}}))
    obs['tracks']=tracks
    return saved,obs


def test_real_pre_hit_plan_stops_ignoring_new_alarm_circle():
    saved,obs=fixture_state()
    before=deepcopy(obs)
    old=MpcAvoider()
    old.last_action=saved['last_action']
    old.ground_static_search=old.ground_reserve_recovery=True
    old.ordinary_air_down_gap=.04
    new=MpcAvoider()
    new.last_action=saved['last_action']
    new.ground_static_search=new.ground_reserve_recovery=True
    new.ordinary_air_down_gap=.04
    new.young_sphere_hazards=True
    assert old.choose(obs)==tuple(saved['expected_original'])
    assert new.choose(obs)==(None,'mpc_wait')
    assert [t.id for t in new._objects(obs) if t.id not in {x.id for x in old._objects(obs)}]==[39,40]
    assert obs==before  # Inclusion does not invent velocity, observations or geometry.


def state_with(track, **extra):
    return dict(time=1.,player=Box(180,200,16,37),tracks=[track],**extra)


def circle(**extra):
    values=dict(id=1,box=Box(280,230,40,40),kind='trap',confidence=.85,
                seen=.92,observations=1,collider_shape='SphereCollider')
    values.update(extra)
    return Track(**values)


def test_candidate_rejects_stale_future_clock_and_weak_circles():
    policy=Avoider()
    policy.young_sphere_hazards=True
    assert policy._objects(state_with(circle()))
    for track in (circle(seen=.8),circle(seen=1.01),circle(confidence=.79)):
        assert not policy._objects(state_with(track))
    assert not policy._objects(state_with(circle(),hazard_confidence=.9))


def test_other_families_and_shapes_keep_confirmation_requirement():
    policy=Avoider()
    policy.young_sphere_hazards=True
    for track in (circle(kind='slice_target'),circle(kind='pinball'),
                  circle(kind='eye_enemy'),circle(collider_shape='BoxCollider')):
        assert not policy._objects(state_with(track))


def test_default_and_already_confirmed_hazards_keep_existing_behavior():
    policy=Avoider()
    assert not policy._objects(state_with(circle()))
    for track in (circle(observations=3),circle(arming=True),circle(active=True)):
        assert policy._objects(state_with(track))==[track]


def test_candidate_does_not_pull_a_passed_circle_back_into_planning():
    policy=Avoider()
    policy.young_sphere_hazards=True
    assert not policy._objects(state_with(circle(box=Box(0,230,40,40))))
