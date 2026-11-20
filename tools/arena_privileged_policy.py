"""Greedy internal-state controller: compute action windows without VM trials."""
from dataclasses import dataclass
import math
import time
import numpy as np
from arena_privileged_model import PlayerModel, hazard_forecasts, clearance, rows


@dataclass(frozen=True)
class Proposal:
    action: str
    delay: float
    window: tuple | None
    predicted_clearance: float
    reason: str
    evidence: dict


class InternalController:
    def __init__(self, *, horizon=1.8, timing_radius=.04, collect_alternatives=False):
        if horizon < 1. or not 0. <= timing_radius <= .05:
            raise ValueError('Use a full action horizon and a <=100ms total timing window')
        self.horizon = horizon
        self.requested_timing_radius = timing_radius
        self.timing_quantum = 1/60
        # The original endpoint transport rounds 40ms outward to three
        # rendered frames (50ms). Plan the interval it will actually test.
        self.timing_radius = math.ceil(timing_radius/self.timing_quantum-1e-8)*self.timing_quantum
        self.last_input = -math.inf
        self.last_inputs = dict(jump=-math.inf,down=-math.inf)
        self.scheduled = None
        self.collect_alternatives = collect_alternatives

    def delivered(self, action, stamp):
        if action != 'none':
            self.last_input = stamp
            self.last_inputs[action] = stamp
        self.scheduled = None

    def decide(self, observation):
        started = time.perf_counter()
        player = PlayerModel(observation)
        times = np.linspace(0., self.horizon, round(self.horizon*120)+1)
        hazards, missing = hazard_forecasts(observation, times, player)
        coupled = any(e['type']=='EnemyPoleaxeWarrior' and e['fields'].get('_enemyState')=='Idle: 0'
                      and not e['fields'].get('_dead') and not e['fields'].get('_isRecycled')
                      for e in rows(observation['enemies'])) or any(e['type'] == 'EnemyStraightBat' and
                      (e['custom'].get('_pointToNinja') or e['custom'].get('_followNinjaY')) and
                      e['fields'].get('_currState','').split(':')[0].lower() in ('none','enterscreen')
                      for e in rows(observation['enemies']))
        stamp = observation['state']['time']
        # Original UI intervals release their input before the next decision.
        # Reserve the keyboard-compatible repeat gap per key, not across K/S.
        # Unity exposes float32 clocks; a rounded 99.99ms must not cost a full
        # extra 50ms decision interval at the nominal 100ms boundary.
        clock_epsilon = max(.00002,2*abs(float(np.spacing(np.float32(stamp)))))
        def input_ready(action,delay):
            previous_late = self.timing_radius if self.collect_alternatives else 0.
            return stamp+delay-(self.last_inputs[action]+previous_late) >= .1-clock_epsilon
        evidence = dict(native_types=sorted({e['type'] for e in rows(observation['enemies'])}),
                        models=sorted({h.source for h in hazards}), unsupported_role=player.unsupported,
                        unsupported_enemies=missing, horizon_seconds=self.horizon,
                        timing_offsets_ms=[-self.timing_radius*1000, self.timing_radius*1000],
                        requested_timing_offsets_ms=[-self.requested_timing_radius*1000,self.requested_timing_radius*1000],
                        timing_quantum_ms=self.timing_quantum*1000,
                        previous_input_reserve_ms=self.timing_radius*1000 if self.collect_alternatives else 0.,
                        native_rollouts=0, restores=0, evaluated=0)
        required_until = self.horizon

        def evaluate(operations, checked_until=None):
            body, motors, valid = player.trajectory(times, operations)
            if operations:
                valid &= input_ready(operations[0][1],operations[0][0])
            evidence['evaluated'] += 1
            actual_hazards = hazard_forecasts(observation, times, player, motors)[0] if coupled else hazards
            interaction_body=player.interaction_bodies(motors) if any(h.interaction for h in actual_hazards) else None
            distances = [clearance(interaction_body if hazard.interaction else body, hazard) for hazard in actual_hazards]
            distances.append(player.terrain_clearances(motors))
            distance = np.minimum.reduce(distances) if distances else np.full(len(times), math.inf)
            collision = np.flatnonzero(distance <= .025)
            # A discontinuous/dead surface is not covered by collision checks
            # against enemies. The original state must reach a real support.
            lowest = min((s.y for s in player.surfaces), default=player.initial.y)-5.
            falling = np.flatnonzero(body[:, 1] < lowest)
            if len(falling):
                collision = np.union1d(collision, falling)
            first = float(times[collision[0]]) if len(collision) else math.inf
            encounter_end = first
            if len(collision):
                first_index = int(collision[0]); last_index = first_index
                while last_index+1 < len(times) and distance[last_index+1] <= .025:
                    last_index += 1
                encounter_end = float(times[last_index])
            reserve = motors[-1].used + (1. if motors[-1].mode not in ('runonline', 'runonlinedown', 'runonground') else 0.)
            local_until = required_until if checked_until is None else checked_until
            recovery = None
            if player.initial.used:
                resting = [i for i,m in enumerate(motors) if times[i] > (operations[0][0] if operations else 0.)
                           and m.mode in ('runonline', 'runonlinedown', 'runonground') and not m.used]
                if resting:
                    recovery = float(times[resting[0]])
                    # Regaining support and both jumps is itself a useful
                    # greedy objective. Require room for another delivered
                    # input, rather than freezing the recovered pose until a
                    # later obstacle that can be handled after the reset.
                    if checked_until is None and operations and operations[0][1] == 'down':
                        local_until = min(local_until, recovery+.1)
            scope = times <= local_until+1e-8
            return dict(safe=valid and first > local_until, full_horizon_safe=valid and not len(collision),
                        clearance=float(distance[scope].min()),
                        first_contact=first, encounter_end=encounter_end,
                        reserve=reserve, end_mode=motors[-1].mode, recovered_at=recovery,
                        required_safe_until_seconds=local_until)

        def finish(action, delay, window, result, reason):
            evidence['compute_ms'] = (time.perf_counter()-started)*1000
            evidence['selected'] = result
            return Proposal(action, delay, window, result['clearance'], reason, evidence)

        baseline = evaluate(())
        evidence['coast'] = baseline
        if math.isfinite(baseline['first_contact']):
            # A greedy decision solves the imminent physical encounter. It
            # must not demand that one flip also solves every later, unrelated
            # obstacle while forbidding the next decision. Keep forecasting
            # the full horizon, but label the local safety scope explicitly.
            required_until = min(self.horizon, baseline['encounter_end']+1/120)
        evidence['required_safe_until_seconds'] = required_until
        # Missing mechanics are not silently converted into stationary boxes.
        # The runner must stop at this boundary instead of publishing a safe
        # operation whose premises omit a nearby enemy.
        unknown_near = [e for e in rows(observation['enemies'])
                        if any(m['id'] == e['id'] for m in missing)
                        and -3 < e['position']['x']-player.initial.x < player.speed*self.horizon+8]
        if player.unsupported or unknown_near:
            return finish('none', 0., None, baseline, 'unsupported_native_mechanism')
        pending = self.scheduled
        def pending_deadline():
            return max(0.,pending['checked_until']-stamp) if 'checked_until' in pending else None
        def signature():
            return {(e['id'],c['id'],e.get('info_identity'),e['fields'].get('m_index'))
                    for e in rows(observation['enemies'])if not e['fields'].get('_dead') and not e['fields'].get('_isRecycled')
                    for c in rows(e['colliders'])if c.get('damage_kind')}
        def proof_changed():
            prior=pending.get('negative_signature')
            return prior is not None and not signature().issubset({tuple(v)for v in prior})
        def remember_negative():
            self.scheduled['negative_signature']=[list(v)for v in sorted(signature(),key=repr)]
            self.scheduled['negative_checked_at']=stamp
        if pending and stamp > pending['due']+self.timing_radius+clock_epsilon:
            self.scheduled = None
            if pending.get('search_choice'):
                return finish('none',0.,None,baseline,'selected_internal_window_invalidated')
            pending = None
        if pending and stamp < pending['due']-clock_epsilon:
            delay = pending['due']-stamp
            checks = [evaluate(((max(0.,delay+d),pending['action']),),pending_deadline())
                      for d in (-self.timing_radius, 0., self.timing_radius)]
            negative_future=delay>=self.timing_radius-clock_epsilon
            if all(r['safe'] for r in checks) and (negative_future or not proof_changed()):
                if negative_future:remember_negative()
                return finish('none', delay, tuple(v-stamp for v in pending['window']),
                              checks[1], 'approach_selected_internal_window' if pending.get('search_choice') else 'approach_center_of_native_safe_window')
            self.scheduled = None
            evidence['pending_rejection']=dict(checks=checks,checked_until=pending.get('checked_until'),visibility_changed=proof_changed())
            if pending.get('search_choice'):
                return finish('none', 0., None, baseline, 'selected_internal_window_invalidated')
            pending=None
        if pending and pending['due']-clock_epsilon <= stamp <= pending['due']+self.timing_radius:
            nominal = evaluate(((0.,pending['action']),),pending_deadline())
            late = evaluate(((self.timing_radius,pending['action']),),pending_deadline())
            if nominal['safe'] and late['safe'] and not proof_changed():
                # Retain the earlier endpoint's proof and absolute deadline.
                # A new enemy/collider lifetime after that endpoint passed
                # invalidates the proof instead of silently clamping it to now.
                evidence['window_origin'] = dict(pending)
                evidence['delivery_check'] = dict(nominal=nominal,late=late)
                window = tuple(v-stamp for v in pending['window'])
                return finish(pending['action'],0.,window,nominal,'execute_center_of_native_safe_window')
            self.scheduled = None
            evidence['pending_rejection']=dict(nominal=nominal,late=late,
                checked_until=pending.get('checked_until'),visibility_changed=proof_changed())
            if pending.get('search_choice'):
                return finish('none',0.,None,baseline,'selected_internal_window_invalidated')
        if baseline['safe'] and player.initial.used < 2:
            self.scheduled = None
            return finish('none', 0., None, baseline, 'native_corridor_clear')

        # Each candidate is a complete physical action and its landing/rope
        # contact. Only its start time varies; there is no key-sequence beam,
        # branch depth, damage-driven rollback, or native engine trial here.
        options = []
        step = 1/30
        latest = min(self.horizon-.1, baseline['first_contact']-.04)
        if not math.isfinite(latest):
            latest = self.horizon-.1
        delays = np.arange(0., max(0., latest)+step/2, step)
        for action in ('jump', 'down'):
            samples = []
            for delay in delays:
                result = evaluate(((float(delay), action),))
                samples.append((float(delay), result))
            groups, current = [], []
            for delay, result in samples:
                if result['safe']:
                    current.append((delay, result))
                elif current:
                    groups.append(current); current = []
            if current:
                groups.append(current)
            for group in groups:
                lo, hi = group[0][0], group[-1][0]
                # A currently safe action needs future timing room too. For a
                # future scheduled action we additionally require the negative
                # endpoint; the past cannot be tested at the current boundary.
                center = (lo+hi)/2
                if hi-lo < 2*self.timing_radius:
                    continue
                if player.initial.used >= 2 and action == 'down':
                    center = lo+self.timing_radius
                nominal = evaluate(((center, action),))
                endpoints = [evaluate(((center+offset, action),))
                             for offset in (-self.timing_radius, self.timing_radius)]
                if not all(r['safe'] for r in endpoints):
                    continue
                margin = min(r['clearance'] for r in [nominal]+endpoints)
                options.append(dict(action=action, delay=center, window=(lo, hi),
                                    result=nominal, margin=margin, endpoints=endpoints,
                                    checked_until_seconds=self.horizon if all(r['full_horizon_safe']for r in [nominal]+endpoints) else min(r['required_safe_until_seconds']for r in [nominal]+endpoints),
                                    survival=min(r['first_contact'] for r in [nominal]+endpoints)))
                if self.collect_alternatives:
                    # Search branches are physically safe windows from this
                    # model, not every key at every 50ms interval. Different
                    # centers can lead to different future jump budgets.
                    for candidate in (lo+self.timing_radius, hi-self.timing_radius):
                        if abs(candidate-center) < .06:
                            continue
                        middle = evaluate(((candidate,action),))
                        ends = [evaluate(((candidate+d,action),))
                                for d in (-self.timing_radius,self.timing_radius)]
                        if middle['safe'] and all(r['safe'] for r in ends):
                            options.append(dict(action=action,delay=candidate,window=(lo,hi),result=middle,
                                checked_until_seconds=self.horizon if all(r['full_horizon_safe']for r in [middle]+ends) else min(r['required_safe_until_seconds']for r in [middle]+ends),
                                margin=min(r['clearance'] for r in [middle]+ends),endpoints=ends,
                                survival=min(r['first_contact'] for r in [middle]+ends)))
        if not options:
            self.scheduled = None
            reason = 'no_safe_action_window' if not baseline['safe'] else 'coast_preserves_safety'
            return finish('none', 0., None, baseline, reason)
        # Prefer returning to support with jump budget, then geometric margin
        # and a broad window. A tiny gain in obstacle clearance must not select
        # an endless sequence of unnecessary jumps in an otherwise clear lane.
        options.sort(key=lambda o: (o['result']['reserve'],
                   o['result']['recovered_at'] if player.initial.used >= 2 and o['result']['recovered_at'] is not None else self.horizon,
                   -min(.5, o['margin']), -min(self.horizon, o['result']['first_contact']),
                   -(o['window'][1]-o['window'][0]), o['delay']))
        best = options[0]
        if self.collect_alternatives:
            evidence['alternatives'] = [dict(action=o['action'],delay=o['delay'],window=o['window'],
                margin=o['margin'],first_contact=o['result']['first_contact'],checked_until_seconds=o['checked_until_seconds'],
                negative_signature=[list(v)for v in sorted(signature(),key=repr)]) for o in options]
        earlier_recovery = (best['result']['recovered_at'] is not None and baseline['recovered_at'] is not None
                            and best['result']['recovered_at'] < baseline['recovered_at']-.1)
        if baseline['safe'] and best['result']['reserve'] >= baseline['reserve'] and not earlier_recovery:
            return finish('none', 0., None, baseline, 'coast_preserves_safety')
        evidence['window_choice'] = {k:v for k,v in best.items() if k != 'result'}
        # Once selected, approach the center of this absolute native-time
        # window. Re-centering it on every observation would continually defer
        # the action until the last possible instant.
        absolute = (stamp+best['window'][0], stamp+best['window'][1])
        if self.scheduled and self.scheduled['action'] == best['action']:
            due = self.scheduled['due']
            if absolute[0] <= due <= absolute[1]:
                best['delay'] = max(0., due-stamp)
            else:
                self.scheduled = None
        elif self.scheduled:
            self.scheduled = None
        if self.scheduled is None:
            self.scheduled = dict(action=best['action'], due=stamp+best['delay'],
                                  window=absolute,origin_stamp=stamp,
                                  checked_until=stamp+best['checked_until_seconds'],
                                  checked_offsets_ms=[-self.timing_radius*1000,self.timing_radius*1000])
            remember_negative()
        delay = best['delay']
        if delay <= clock_epsilon:
            return finish(best['action'], 0., best['window'], best['result'], 'execute_center_of_native_safe_window')
        return finish('none', delay, best['window'], best['result'], 'approach_center_of_native_safe_window')
