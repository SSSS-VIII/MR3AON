"""Internal-state decisions, without visual inference or game branch trials."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel, Surface, hazard_forecasts, clearance, rows, timer_ticks
from arena_privileged_policy import InternalController


@pytest.fixture
def native():
    return json.loads((Path(__file__).parent/'fixtures/arena-privileged-native.json').read_text())


def test_real_rope_encounter_has_proactive_window_without_game_trials(native):
    result = InternalController().decide(native)
    assert result.reason == 'approach_center_of_native_safe_window'
    assert result.window[1]-result.window[0] >= .08
    assert 0 < result.delay < result.evidence['coast']['first_contact']
    assert result.evidence['native_rollouts'] == result.evidence['restores'] == 0
    assert result.evidence['selected']['safe']
    # Solving the immediate encounter is explicitly distinct from freezing
    # that pose through every later obstacle without another decision.
    assert not result.evidence['selected']['full_horizon_safe']


def test_scheduled_window_does_not_slide_forever_into_the_future(native):
    controller = InternalController()
    first = controller.decide(native)
    due = controller.scheduled['due']
    moved = deepcopy(native)
    moved['state']['time'] += .05
    # This stationary-world fixture isolates the scheduling clock rather than
    # pretending to be a physically advanced original state.
    second = controller.decide(moved)
    assert controller.scheduled['due'] == due
    assert second.delay == pytest.approx(first.delay-.05)


def test_native_jump_velocity_and_gravity_change_the_forecast(native):
    native['state']['physics'] = 'jump: 14'
    native['role']['velocity']['y'] = 20.
    times = np.array([0., .01])
    body, states, valid = PlayerModel(native).trajectory(times)
    assert valid
    assert states[-1].y-native['state']['position']['y'] == pytest.approx(.2-.5*25*3.5*.01**2)
    assert states[-1].vy == pytest.approx(20.-25*3.5*.01)
    native['role']['data']['_upGravity1'] = -10.
    _, states2, _ = PlayerModel(native).trajectory(times)
    assert states2[-1].y > states[-1].y


def test_finite_rope_endpoint_is_not_extrapolated(native):
    model = PlayerModel(native)
    m = model.initial
    model.surfaces = [Surface(m.support, m.x-1, m.x+1, m.y-.75, 0., True)]
    model.initial.mode = 'runonline'
    _, states, _ = model.trajectory(np.array([0., .02, .04, .08, .12]))
    assert states[1].y == pytest.approx(states[0].y)
    assert states[-1].mode == 'fallfromrun'


def test_second_jump_exhaustion_and_midair_down_are_native_actions(native):
    model = PlayerModel(native)
    model.initial.mode = 'fall2'; model.initial.used = 2; model.initial.y = 3.
    times = np.linspace(0., .2, 25)
    _, _, valid = model.trajectory(times, ((0., 'jump'),))
    assert not valid
    _, states, valid = model.trajectory(times, ((0., 'down'),))
    assert valid and states[-1].y < 3.
    assert states[-1].mode in ('rolltolinedown', 'runonlinedown')


def test_true_bat_ready_timer_changes_launch_not_a_visual_clock(native):
    ready = next(e for e in native['enemies'] if e['fields']['_currState'].startswith('ready:'))
    native['enemies'] = [ready]
    times = np.array([0., .1, .2])
    a, missing = hazard_forecasts(native, times, PlayerModel(native))
    assert not missing
    ready['fields']['_currStateTime'] += .2
    b, missing = hazard_forecasts(native, times, PlayerModel(native))
    assert not missing
    assert b[0].centers[-1, 0] > a[0].centers[-1, 0]


def test_fast_projectile_crossing_between_samples_is_dangerous(native):
    from arena_privileged_model import Hazard
    body = np.array([[0.,0.,.2,.3],[0.,0.,.2,.3]])
    hazard = Hazard(1,1,'test',np.array([[2.,0.],[-2.,0.]]),np.full((2,2),.05),
                    np.array([True,True]),'fixture')
    assert clearance(body, hazard)[-1] < 0


def test_unknown_native_enemy_cannot_be_silently_ignored(native):
    native['enemies'][0]['type'] = 'UnmodeledNativeTrap'
    native['enemies'][0]['position']['x'] = native['state']['position']['x']+3
    result = InternalController().decide(native)
    assert result.reason == 'unsupported_native_mechanism'
    assert result.evidence['unsupported_enemies'][0]['type'] == 'UnmodeledNativeTrap'


@pytest.mark.parametrize('ahead,near',[(3.,True),(200.,False)])
def test_unknown_offset_damage_shape_is_checked_separately_from_parent_root(native,ahead,near):
    enemy=native['enemies'][0];native['enemies']=[enemy]
    enemy['type']='UnmodeledNativeLink'
    x=native['state']['position']['x'];enemy['position']['x']=x-60
    for c in enemy['colliders']:
        delta=x+ahead-c['center']['x'];c['center']['x']+=delta
        for p in rows(c.get('quad')):p['x']+=delta
    proposal=InternalController().decide(native)
    assert (proposal.reason=='unsupported_native_mechanism')is near


def test_unknown_disabled_authored_link_shape_still_requires_a_future_model(native):
    enemy=native['enemies'][0];native['enemies']=[enemy];enemy['type']='UnmodeledNativeLink'
    x=native['state']['position']['x'];enemy['position']['x']=x-60
    enemy['colliders']=[dict(id=-1,damage_kind='enemy_callback',enabled=True,active=False,
        center=dict(x=x-60,y=0),extents=dict(x=0,y=0),
        quad=[dict(x=x+a,y=b)for a,b in ((2,0),(4,0),(4,1),(2,1))])]
    assert InternalController().decide(native).reason=='unsupported_native_mechanism'


def test_input_not_mutated_and_empty_lua_arrays_are_explicit(native):
    original = deepcopy(native)
    InternalController().decide(native)
    assert native == original
    assert rows({}) == []
    with pytest.raises(ValueError):
        rows({'not':'a sequence'})


def test_bamboo_warning_is_not_damage_and_native_lock_timer_controls_flight():
    observation = json.loads((Path(__file__).parent/'fixtures/arena-privileged-bamboo.json').read_text())
    # This older native fixture did not export the launch projection. This
    # test checks activation only; supply an explicit synthetic projection.
    observation['camera']['reflection_right'] = dict(x=100., y=0., z=0.)
    enemy = observation['enemies'][0]
    enemy['fields']['_enemyState'] = 'aimLock: 1'
    enemy['fields']['_currStateTime'] = .1
    # Use a zero physics age so the boundary is the countdown lattice.
    enemy['fields']['_lastFixedUpdateTime'] = observation['state']['time']
    times = np.array([0., .59, .65])
    hazards, missing = hazard_forecasts(observation, times, PlayerModel(observation))
    assert not missing and len(hazards) == 1
    assert hazards[0].active.tolist() == [False, False, True]
    attack = next(c for c in enemy['colliders'] if c['id'] == hazards[0].id)
    assert attack['name'] == 'Attack'
    assert not attack['active']  # Original not-yet-enabled projectile shape.
    enemy['fields']['_enemyState'] = 'readyAttack: 2'
    hazards, _ = hazard_forecasts(observation, times, PlayerModel(observation))
    assert hazards[0].active.tolist() == [False, True, True]


def test_fall_restores_normal_capsule_and_second_jump_uses_roll_capsule(native):
    model = PlayerModel(native)
    m = model.initial
    m.mode = 'jump2'
    _, _, radius, spine = model.body_at(m)
    assert radius == pytest.approx(.126)
    assert spine == 0
    m.mode = 'fall2'
    _, _, radius, spine = model.body_at(m)
    assert radius == pytest.approx(.2)
    assert 2*(radius+spine) == pytest.approx(.936)


def test_air_down_keeps_entry_speed_across_rope_top(native):
    model = PlayerModel(native)
    model.initial.mode = 'fall2'; model.initial.used = 2
    model.initial.y = 2.
    times = np.linspace(0., .13, 157)
    _, states, valid = model.trajectory(times, ((0., 'down'),))
    assert valid
    middle = [m for m in states if -.5 < m.y < .5]
    assert middle and all(abs(m.vy) == pytest.approx(28.) for m in middle)


def test_spent_jump_can_recover_before_the_next_independent_encounter(native):
    native['state']['physics'] = 'fall2: 17'
    native['state']['position']['y'] = 3.
    native['role']['velocity']['y'] = -1.
    # Native fixtures retain the actual shape; move its center with the root.
    native['role']['colliders'][0]['center']['y'] = 3.
    native['enemies'] = []
    result = InternalController().decide(native)
    assert result.evidence['selected']['recovered_at'] is not None
    assert result.reason in ('approach_center_of_native_safe_window','execute_center_of_native_safe_window')


def test_original_float_countdown_does_not_round_point_three_to_fifteen_ticks():
    assert timer_ticks(.3,.02) == 16
    assert timer_ticks(0.,.02) == 1
    assert timer_ticks(0.,.02,False) == 0
    assert timer_ticks(.5,.02) == 25


def test_forecasts_match_recorded_original_ui_intervals():
    captures=json.loads((Path(__file__).parent/'fixtures/arena-privileged-motor.json').read_text())
    for capture in captures:
        before,after=capture['before'],capture['after']
        elapsed=after['time']-before['state']['time']
        model=PlayerModel(before)
        bodies,_,valid=model.trajectory(np.linspace(0.,elapsed,round(elapsed*120)+1),((0.,capture['action']),))
        actual=next(c for c in after['colliders'] if c['name']=='Role'and c['enabled'])
        assert valid
        assert abs(bodies[-1,0]-actual['center']['x']) < .06
        assert abs(bodies[-1,1]-actual['center']['y']) < .06


def test_unlocked_targeting_bat_depends_on_candidate_role_trajectory(native):
    enemy=next(e for e in native['enemies'] if e['fields']['_currState'].startswith('enterScreen:'))
    native['enemies']=[enemy];enemy['custom']['_pointToNinja']=True
    model=PlayerModel(native);times=np.linspace(0.,1.8,217)
    _,coast,_=model.trajectory(times)
    _,flip,_=model.trajectory(times,((0.,'jump'),))
    a,missing=hazard_forecasts(native,times,model,coast)
    b,missing2=hazard_forecasts(native,times,model,flip)
    assert not missing and not missing2
    assert abs(a[0].centers[-1,1]-b[0].centers[-1,1]) > .1


def test_candidate_specific_missing_forecast_is_not_an_empty_safe_lane(native,monkeypatch):
    import arena_privileged_policy as policy
    enemy=next(e for e in native['enemies']if e['fields']['_currState'].startswith('enterScreen:'))
    enemy['custom']['_pointToNinja']=True
    def reject_candidate(observation,times,player,states=None):
        if states is not None:
            return [],[dict(id=enemy['id'],type=enemy['type'],reason='candidate_motion_not_supported')]
        return hazard_forecasts(observation,times,player)
    monkeypatch.setattr(policy,'hazard_forecasts',reject_candidate)
    proposal=InternalController().decide(native)
    assert proposal.reason=='no_safe_action_window'
    assert proposal.action=='none' and not proposal.evidence['selected']['safe']
    assert proposal.evidence['candidate_forecast_rejections'][enemy['type']+':candidate_motion_not_supported']>0


def test_original_bamboo_window_executes_when_early_endpoint_has_passed():
    pair=json.loads((Path(__file__).parent/'fixtures/arena-privileged-pending.json').read_text())
    controller=InternalController()
    # This is the proposal actually recorded at the earlier boundary. The
    # scheduling regression must remain protected if action ranking improves.
    stamp=pair['before']['state']['time']
    controller.scheduled=dict(action='jump',due=stamp+.05,window=(stamp,stamp+.1),
                              origin_stamp=stamp,checked_offsets_ms=[-40.,40.])
    # Retain the actual earlier trajectory while its endpoint is still
    # available. A timestamp alone is not a proof of the past endpoint.
    approach=controller.decide(pair['before'])
    assert approach.action=='none' and controller.scheduled is not None
    execution=controller.decide(pair['now'])
    assert execution.action=='jump'
    assert execution.reason=='execute_center_of_native_safe_window'
    assert execution.window[0] < 0
    assert execution.evidence['delivery_check']['nominal']['safe']
    assert execution.evidence['delivery_check']['late']['safe']


def test_native_sphere_does_not_inherit_aabb_corner_collision():
    from arena_privileged_model import Hazard
    body=np.array([[0.,0.,.2,.3],[0.,0.,.2,.3]])
    centers=np.array([[.33,.63],[.33,.63]])
    box=Hazard(1,1,'native_sphere',centers,np.full((2,2),.2),np.ones(2,bool),'fixture')
    sphere=deepcopy(box);sphere.geometry='sphere'
    assert clearance(body,box).min()<0
    assert clearance(body,sphere).min()>0


def test_current_air_ground_reference_wins_over_base_ground(native):
    native['state']['physics']='runOnGround: 5'
    native['state']['position']['y']=3.75
    native['role']['colliders'][0]['center']['y']=3.75
    x=native['state']['position']['x']
    native['platforms']=[dict(id=123,is_current=True,fields={},info=dict(
        _leftX=x-3,_rightX=x+3,_topY=3.,_bottomY=2.8,_speedX=0.,_speedY=0.))]
    model=PlayerModel(native)
    _,states,valid=model.trajectory(np.array([0.,.02]))
    assert valid and model.initial.support==123
    assert states[-1].y==pytest.approx(3.75)


def test_stale_ground_slope_ratio_does_not_rescale_flat_rope(native):
    # The original field persists after leaving a descent. It is a ground
    # target multiplier, not a global horizontal movement multiplier.
    displacements=[]
    for ratio in (1.,1.8):
        observation=deepcopy(native)
        observation['role'].setdefault('fields',{})['_slopeSpeedRatio']=ratio
        model=PlayerModel(observation)
        _,states,_=model.trajectory(np.array([0.,.02]))
        displacements.append(states[-1].x-states[0].x)
    assert displacements[0]==pytest.approx(displacements[1])
    assert displacements[0]==pytest.approx(native['state']['speed']*.02)


def test_original_spider_drop_flex_and_interpolation_pairs():
    from arena_privileged_model import spider_positions
    pairs=json.loads((Path(__file__).parent/'fixtures/arena-privileged-spider.json').read_text())
    assert len(pairs)>=5
    for pair in pairs:
        ys=spider_positions(pair['enemy'],np.array([0.,pair['seconds']]),stamp=pair['stamp'],tick=pair['tick'])
        assert abs(ys[0]-pair['enemy']['position']['y'])<1e-5
        assert abs(ys[-1]-pair['expected_y'])<.025


def test_original_up_down_reversals_are_legal_without_waiting_for_contact():
    pairs=json.loads((Path(__file__).parent/'fixtures/arena-privileged-reversals.json').read_text())
    seen=set()
    for pair in pairs:
        model=PlayerModel(pair['before']);elapsed=pair['after']['time']-pair['before']['state']['time']
        bodies,motors,valid=model.trajectory(np.linspace(0.,elapsed,round(elapsed*120)+1),((0.,pair['action']),))
        assert valid
        assert abs(motors[-1].y-pair['after']['position']['y'])<.18
        seen.add((pair['before']['state']['physics'].split(':')[0],pair['action']))
    assert ('rollToLineOn','down') in seen
    assert ('rollToLineDown','jump') in seen


@pytest.mark.parametrize('previous,gap,expected',[
    ('down',.05,'jump'),('jump',.099990845,'jump'),('jump',.05,'none')])
def test_input_repeat_constraints_are_per_key_and_float_clock_tolerant(previous,gap,expected):
    pair=json.loads((Path(__file__).parent/'fixtures/arena-privileged-pending.json').read_text())
    controller=InternalController();now=pair['now']['state']['time'];origin=pair['before']['state']['time']
    # Isolate delivery availability using a known physically safe pending
    # operation. The original UI reversal capture proves alternate keys work
    # at 50ms; equal keys still respect the future sender's repeat interval.
    controller.scheduled=dict(action='jump',due=origin+.05,window=(origin,origin+.1),
                              origin_stamp=origin,checked_offsets_ms=[-40.,40.])
    controller.decide(pair['before'])
    pending=controller.scheduled
    controller.delivered(previous,now-gap)
    # This test isolates the sender repeat gate from the already checked
    # trajectory; real intervening delivery always clears a pending plan.
    controller.scheduled=pending
    result=controller.decide(pair['now'])
    assert result.action==expected
