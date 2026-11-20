"""Greedy internal-state controller: compute action windows without VM trials."""
from copy import copy
from dataclasses import dataclass
import math
import time
import numpy as np
from arena_privileged_model import PlayerModel, hazard_forecasts, clearance, rows
from arena_privileged_families import collectible_kind,progression_marker,PENDING_BLADE_NAMES


@dataclass(frozen=True)
class Proposal:
    action: str
    delay: float
    window: tuple | None
    predicted_clearance: float
    reason: str
    evidence: dict


def witness_operations(model,times,first,witness,offset=0.):
    """Anchor the next input to world X, independently of the first's jitter."""
    _,states,_=model.trajectory(times,(first,))
    positions=np.array([m.x for m in states]);target=witness['world_x']
    if target<=positions[0]or target>positions[-1]or np.any(np.diff(positions)<-1e-5):return None
    second=float(np.interp(target,positions,times))+offset
    if second<=first[0]or second<0:return None
    return (first,(second,witness['action']))


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
        forecast_cache={}
        hazards, missing = hazard_forecasts(observation, times, player,forecast_cache=forecast_cache)
        static_pending={h.enemy for h in hazards if h.kind in PENDING_BLADE_NAMES}
        pending_coupled=any(not e['sync_blocked']and
            (e['info']['_enemyType'].split(':',1)[0]not in PENDING_BLADE_NAMES or e['id']not in static_pending)
            for e in rows(observation.get('pending_enemies')))
        spring_camera_coupled=bool(player.spring_launches)and any(e['type']in (
            'EnemyFlyBamboo','EnemyBullutFireRobot','EnemyBullutLaser','EnemyAlarmShooter')
            for e in rows(observation['enemies'])if not e['fields'].get('_dead')and not e['fields'].get('_isRecycled'))
        coupled = any(e['type']=='EnemyPoleaxeWarrior' and e['fields'].get('_enemyState')=='Idle: 0'
                      and not e['fields'].get('_dead') and not e['fields'].get('_isRecycled')
                      for e in rows(observation['enemies'])) or any(e['type'] == 'EnemyStraightBat' and
                      (e['custom'].get('_pointToNinja') or e['custom'].get('_followNinjaY')) and
                      e['fields'].get('_currState','').split(':')[0].lower() in ('none','enterscreen')
                      for e in rows(observation['enemies'])) or any(
                      e['type']=='EnemyFlyBamboo'and e['custom'].get('_followNinja') or
                      e['type'] in ('EnemyStraightBack','EnemySmallSword','EnemyBullutFireRobot','EnemyBullutLaser','EnemyAlarmShooter') or
                      e['type']in ('EnemySpider','EnemyMuppetBomb') and e['fields'].get('_enemyState')=='none: 9' or
                      e['type']=='EnemyRollingBase' and e['fields'].get('_enemyState','').rsplit(':',1)[-1].strip()=='0' or
                      e['type']=='EnemyBrambles' and e['fields'].get('_currState','').rsplit(':',1)[-1].strip()=='0' or
                      e['type']=='EnemyRockTiger' and e['fields'].get('currState','').rsplit(':',1)[-1].strip() in ('1','2') or
                      e['type']=='EnemyPiranha' and e['fields'].get('_enemyState','').rsplit(':',1)[-1].strip() in ('0','1')
                      for e in rows(observation['enemies'])if not e['fields'].get('_dead') and not e['fields'].get('_isRecycled')) or pending_coupled or spring_camera_coupled
        stamp = observation['state']['time']
        # Original UI intervals release their input before the next decision.
        # Reserve the keyboard-compatible repeat gap per key, not across K/S.
        # Unity exposes float32 clocks; a rounded 99.99ms must not cost a full
        # extra 50ms decision interval at the nominal 100ms boundary.
        clock_epsilon = max(.00002,2*abs(float(np.spacing(np.float32(stamp)))))
        def input_ready(action,delay):
            previous_late = self.timing_radius if self.collect_alternatives else 0.
            return stamp+delay-(self.last_inputs[action]+previous_late) >= .1-clock_epsilon
        evidence = dict(coupled_forecasts=bool(coupled),native_types=sorted({e['type'] for e in rows(observation['enemies'])}),
                        pending_types=sorted({e['info']['_enemyType']for e in rows(observation.get('pending_enemies'))}),
                        models=sorted({h.source for h in hazards}), unsupported_role=player.unsupported,
                        collectibles=[dict(id=e['id'],kind=collectible_kind(e),position=e['position'])
                                      for e in rows(observation['enemies'])if collectible_kind(e)
                                      and not e['fields'].get('_dead') and not e['fields'].get('_isRecycled')],
                        progression_markers=[dict(id=e['id'],kind=progression_marker(e),position=e['position'])
                                             for e in rows(observation.get('mechanism_items'))if progression_marker(e)],
                        special_task=observation.get('special_task'),
                        unsupported_enemies=missing, horizon_seconds=self.horizon,
                        timing_offsets_ms=[-self.timing_radius*1000, self.timing_radius*1000],
                        requested_timing_offsets_ms=[-self.requested_timing_radius*1000,self.requested_timing_radius*1000],
                        timing_quantum_ms=self.timing_quantum*1000,
                        previous_input_reserve_ms=self.timing_radius*1000 if self.collect_alternatives else 0.,
                        native_rollouts=0, restores=0, evaluated=0)
        original_missing={(m['id'],m['type'],m['reason'])for m in missing}
        required_until = self.horizon

        def evaluate(operations, checked_until=None, rollout=None, forecast_player=None):
            model = forecast_player or player
            body, motors, valid = rollout if rollout is not None else model.trajectory(times, operations)
            previous=dict(self.last_inputs)
            for delay,action in operations:
                # Only prior delivered inputs carry their endpoint reserve.
                # The planned operations here already have concrete jitter.
                reserve=self.timing_radius if self.collect_alternatives and previous[action]==self.last_inputs[action]else 0.
                valid &= stamp+delay-(previous[action]+reserve)>=.1-clock_epsilon
                previous[action]=stamp+delay
            evidence['evaluated'] += 1
            if coupled or forecast_player is not None:
                actual_hazards,unmapped=hazard_forecasts(observation,times,model,motors,forecast_cache=forecast_cache)
                new_missing=[m for m in unmapped if (m['id'],m['type'],m['reason'])not in original_missing]
                # A rejected candidate-specific forecast is not an empty
                # safe lane. Keep the guard for speed/target changes instead
                # of silently dropping the very obstacle being replanned.
                valid &= not new_missing
                if new_missing:
                    counts=evidence.setdefault('candidate_forecast_rejections',{})
                    for m in new_missing:
                        key=m['type']+':'+m['reason'];counts[key]=counts.get(key,0)+1
            else:
                actual_hazards=hazards
            interaction_body=model.interaction_bodies(motors) if any(h.interaction for h in actual_hazards) else None
            distances = [clearance(interaction_body if hazard.interaction else body, hazard) for hazard in actual_hazards]
            distances.append(model.terrain_clearances(motors))
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
                        player_x_range=(float(np.min(body[:,0]-body[:,2])),float(np.max(body[:,0]+body[:,2]))),
                        required_safe_until_seconds=local_until)

        def combine_checks(checks,nominal=0):
            result=dict(checks[nominal])
            result.update(safe=all(r['safe']for r in checks),
                full_horizon_safe=all(r.get('full_horizon_safe',False)for r in checks),
                clearance=min(r.get('clearance',-math.inf)for r in checks),
                first_contact=min(r.get('first_contact',0.)for r in checks))
            return result

        def planned_check(delay,action,witness=None,checked_until=None):
            if witness is None:return evaluate(((max(0.,delay),action),),checked_until)
            checks=[]
            for offset in (0.,-self.timing_radius,self.timing_radius):
                operations=witness_operations(player,times,(max(0.,delay),action),witness,offset)
                if operations is None:
                    checks.append(dict(safe=False,full_horizon_safe=False,clearance=-math.inf,first_contact=0.))
                else:checks.append(evaluate(operations,checked_until))
            return combine_checks(checks)

        continuation_cache={}
        def continuation_exists(delay,action):
            """Retain a complete independently jittered follow-up witness.

            A merely nominal continuation cannot justify approaching a first
            key. Both keys must have their own original timing endpoints in
            the same physical future; native certification remains separate.
            """
            key=(delay,action)
            if key in continuation_cache:return continuation_cache[key]is not None
            result=evaluate(((delay,action),),self.horizon)
            ends=[evaluate(((max(0.,delay+d),action),),self.horizon)
                  for d in (-self.timing_radius,self.timing_radius)]
            if all(r['full_horizon_safe']for r in [result]+ends):
                continuation_cache[key]=dict(nominal=result,endpoints=ends,witness=None);return True
            _,states,_=player.trajectory(times,((delay,action),))
            end=min(self.horizon-.1,result['first_contact']-self.timing_radius)
            start=math.ceil((delay+.1)/.05-1e-8)*.05
            for when in np.arange(start,end+1e-8,.05):
                ix=min(len(times)-1,int(np.searchsorted(times,when)))
                for followup in ('jump','down'):
                    if not player.action(copy(states[ix]),followup,float(when)):continue
                    checked=evaluate(((delay,action),(float(when),followup)),self.horizon)
                    if checked['full_horizon_safe']:
                        target=float(np.interp(when,times,[m.x for m in states]))
                        witness=dict(action=followup,world_x=target)
                        checks=[planned_check(delay+d,action,witness,self.horizon)
                                for d in (0.,-self.timing_radius,self.timing_radius)]
                        if not all(r['full_horizon_safe']for r in checks):continue
                        continuation_cache[key]=dict(nominal=checks[0],endpoints=checks[1:],witness=witness)
                        return True
            continuation_cache[key]=None
            evidence.setdefault('locally_safe_dead_ends',[]).append(dict(action=action,delay=delay))
            return False

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
        left,right=baseline['player_x_range'];left-=3.;right+=8.
        def reaches_actor_corridor(enemy):
            if left<enemy['position']['x']<right:return True
            # A connected beam or a bone-followed weapon can be far from its
            # parent's spawn root. Missing motion must not make its current
            # authored damage footprint disappear from the safety boundary.
            for collider in rows(enemy.get('colliders'))+rows(enemy.get('grown_colliders')):
                if not(collider.get('damage_kind')or collider.get('native_movement_callback')):continue
                quad=rows(collider.get('quad'))
                a=min(p['x']for p in quad)if quad else collider['center']['x']-collider['extents']['x']
                b=max(p['x']for p in quad)if quad else collider['center']['x']+collider['extents']['x']
                if not math.isfinite(a+b)or a<=right and b>=left:return True
            return False
        unknown_near = [e for e in rows(observation['enemies'])
                        if any(m['id'] == e['id'] for m in missing)and reaches_actor_corridor(e)]
        pending_missing=[m for m in missing if str(m['id']).startswith('pending')]
        if player.unsupported or unknown_near or pending_missing:
            return finish('none', 0., None, baseline, 'unsupported_native_mechanism')
        pending = self.scheduled
        def pending_deadline():
            return max(0.,pending['checked_until']-stamp) if 'checked_until' in pending else None
        def signature():
            return {(e['id'],c['id'],e.get('info_identity'),e['fields'].get('m_index'))
                    for e in rows(observation['enemies'])if not e['fields'].get('_dead') and not e['fields'].get('_isRecycled')
                    for c in rows(e['colliders'])if c.get('damage_kind')or c.get('native_movement_callback')}
        def proof_changed():
            prior=pending.get('negative_signature')
            return prior is not None and not signature().issubset({tuple(v)for v in prior})
        def remember_negative():
            self.scheduled['negative_signature']=[list(v)for v in sorted(signature(),key=repr)]
            self.scheduled['negative_checked_at']=stamp
            self.scheduled['_negative_model']=player
            self.scheduled['_negative_origin']=stamp
            self.scheduled['_negative_operation']=(max(0.,self.scheduled['due']-stamp-self.timing_radius),self.scheduled['action'])
            if self.scheduled.get('witness'):
                self.scheduled['_negative_operations']=[witness_operations(player,times,
                    self.scheduled['_negative_operation'],self.scheduled['witness'],offset)
                    for offset in (0.,-self.timing_radius,self.timing_radius)]
        def retained_negative():
            origin=pending.get('_negative_origin')
            if origin is None:
                return dict(safe=False,reason='earlier_endpoint_model_missing')
            elapsed=stamp-origin
            prior=pending['_negative_model']
            if prior.tick!=player.tick or prior.data!=player.data:
                return dict(safe=False,reason='earlier_endpoint_motion_parameters_changed')
            _,coast,_=prior.trajectory(np.array([0.,elapsed]))
            if np.hypot(coast[-1].x-player.initial.x,coast[-1].y-player.initial.y)>.025:
                return dict(safe=False,reason='unchanged_prefix_disagrees_with_native_state')
            query=elapsed+times
            mesh=np.unique(np.r_[np.linspace(0.,query[-1],math.ceil(query[-1]*120)+1),query])
            plans=pending.get('_negative_operations',[(pending['_negative_operation'],)])
            if not plans or any(p is None for p in plans):return dict(safe=False,reason='earlier_witness_anchor_missing')
            results=[]
            for operations in plans:
                bodies,motors,valid=prior.trajectory(mesh,operations)
                indices=np.searchsorted(mesh,query);motors=[motors[i]for i in indices]
                projected=copy(player);projected.initial=motors[0]
                results.append(evaluate((),pending_deadline(),(bodies[indices],motors,valid),projected))
            result=combine_checks(results)
            evidence['retained_early_endpoint']=dict(origin_stamp=origin,seconds_since_origin=elapsed,
                visibility_changed=proof_changed(),result=result)
            return result
        if pending and stamp > pending['due']+self.timing_radius+clock_epsilon:
            self.scheduled = None
            if pending.get('search_choice'):
                return finish('none',0.,None,baseline,'selected_internal_window_invalidated')
            pending = None
        if pending and stamp < pending['due']-clock_epsilon:
            delay = pending['due']-stamp
            checks = [planned_check(max(0.,delay+d),pending['action'],pending.get('witness'),pending_deadline())
                      for d in (-self.timing_radius, 0., self.timing_radius)]
            negative_future=delay>=self.timing_radius-clock_epsilon
            if not negative_future:checks[0]=retained_negative()
            if all(r['safe'] for r in checks):
                if negative_future:remember_negative()
                return finish('none', delay, tuple(v-stamp for v in pending['window']),
                              checks[1], 'approach_selected_internal_window' if pending.get('search_choice') else 'approach_center_of_native_safe_window')
            self.scheduled = None
            evidence['pending_rejection']=dict(checks=checks,checked_until=pending.get('checked_until'),visibility_changed=proof_changed())
            if pending.get('search_choice'):
                return finish('none', 0., None, baseline, 'selected_internal_window_invalidated')
            pending=None
        if pending and pending['due']-clock_epsilon <= stamp <= pending['due']+self.timing_radius:
            nominal = planned_check(0.,pending['action'],pending.get('witness'),pending_deadline())
            late = planned_check(self.timing_radius,pending['action'],pending.get('witness'),pending_deadline())
            early=retained_negative()
            viable=(pending.get('witness')or nominal['full_horizon_safe']or continuation_exists(0.,pending['action']))
            if nominal['safe'] and late['safe'] and early['safe'] and viable:
                # Re-evaluate the retained earlier trajectory against the
                # newly observed world. Do not replace an already-past key
                # with a new key at the current decision boundary.
                evidence['window_origin'] = {k:v for k,v in pending.items()if not k.startswith('_negative_')}
                evidence['delivery_check'] = dict(nominal=nominal,late=late)
                window = tuple(v-stamp for v in pending['window'])
                return finish(pending['action'],0.,window,nominal,'execute_center_of_native_safe_window')
            self.scheduled = None
            evidence['pending_rejection']=dict(nominal=nominal,late=late,early=early,
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
                proof=None
                if not all(r['full_horizon_safe']for r in [nominal]+endpoints):
                    if not continuation_exists(center,action):continue
                    proof=continuation_cache[(center,action)]
                    nominal,endpoints=proof['nominal'],proof['endpoints']
                margin = min(r['clearance'] for r in [nominal]+endpoints)
                options.append(dict(action=action, delay=center, window=(lo, hi),
                                    result=nominal, margin=margin, endpoints=endpoints,
                                    checked_until_seconds=self.horizon if all(r['full_horizon_safe']for r in [nominal]+endpoints) else min(r['required_safe_until_seconds']for r in [nominal]+endpoints),
                                    survival=min(r['first_contact'] for r in [nominal]+endpoints),
                                    **(dict(witness=proof['witness'])if proof and proof['witness']else{})))
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
                            proof=None
                            if not all(r['full_horizon_safe']for r in [middle]+ends):
                                if not continuation_exists(candidate,action):continue
                                proof=continuation_cache[(candidate,action)]
                                middle,ends=proof['nominal'],proof['endpoints']
                            options.append(dict(action=action,delay=candidate,window=(lo,hi),result=middle,
                                checked_until_seconds=self.horizon if all(r['full_horizon_safe']for r in [middle]+ends) else min(r['required_safe_until_seconds']for r in [middle]+ends),
                                margin=min(r['clearance'] for r in [middle]+ends),endpoints=ends,
                                survival=min(r['first_contact'] for r in [middle]+ends),
                                **(dict(witness=proof['witness'])if proof and proof['witness']else{})))
        if not options and not baseline['safe']:
            # A single flip cannot express rope-below -> rope-above -> jump.
            # Search short legal maneuvers in the internal model only, keeping
            # the next key as a world-X witness. It is re-evaluated while
            # approaching the first key, then replanned from the native state.
            latest_first=min(self.horizon-.4,baseline['first_contact']-.1-self.timing_radius)
            evidence['joint_witness_candidates']=0
            for first_delay in np.arange(.1,max(.1,latest_first)+1e-8,.2)if latest_first>=.1 else ():
                _,prefix,valid=player.trajectory(np.array([0.,float(first_delay)]))
                if not valid:continue
                for first_action in ('jump','down'):
                    if not input_ready(first_action,float(first_delay)-self.timing_radius):continue
                    if not player.action(copy(prefix[-1]),first_action,float(first_delay)):continue
                    _,first_states,_=player.trajectory(times,((float(first_delay),first_action),))
                    for second_action in ('jump','down'):
                        start=first_delay+(.1+2*self.timing_radius if first_action==second_action else .1)
                        start=math.ceil(start/.05-1e-8)*.05
                        samples=[]
                        for second_delay in np.arange(start,self.horizon-.3+1e-8,.05):
                            ix=min(len(times)-1,int(np.searchsorted(times,second_delay)))
                            if not player.action(copy(first_states[ix]),second_action,float(second_delay)):
                                samples.append((float(second_delay),dict(safe=False)));continue
                            result=evaluate(((float(first_delay),first_action),(float(second_delay),second_action)),self.horizon)
                            evidence['joint_witness_candidates']+=1
                            samples.append((float(second_delay),result))
                        groups=[];group=[]
                        for delay,result in samples:
                            if result['safe']:group.append((delay,result))
                            elif group:groups.append(group);group=[]
                        if group:groups.append(group)
                        for group in groups:
                            lo,hi=group[0][0],group[-1][0]
                            if hi-lo<2*self.timing_radius-clock_epsilon:continue
                            second_delay=(lo+hi)/2
                            target=float(np.interp(second_delay,times,[m.x for m in first_states]))
                            witness=dict(action=second_action,world_x=target)
                            nominal=planned_check(float(first_delay),first_action,witness,self.horizon)
                            ends=[planned_check(float(first_delay)+offset,first_action,witness,self.horizon)
                                  for offset in (-self.timing_radius,self.timing_radius)]
                            if not nominal['safe']or not all(r['safe']for r in ends):continue
                            options.append(dict(action=first_action,delay=float(first_delay),
                                window=(float(first_delay)-self.timing_radius,float(first_delay)+self.timing_radius),
                                result=nominal,margin=min(r['clearance']for r in [nominal]+ends),
                                endpoints=ends,checked_until_seconds=self.horizon,
                                survival=min(r['first_contact']for r in [nominal]+ends),witness=witness))
                    if options:break
                if options:break
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
                negative_signature=[list(v)for v in sorted(signature(),key=repr)],
                **(dict(witness=o['witness'])if o.get('witness')else{})) for o in options]
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
            if best.get('witness'):self.scheduled['witness']=dict(best['witness'])
            remember_negative()
        delay = best['delay']
        if delay <= clock_epsilon:
            return finish(best['action'], 0., best['window'], best['result'], 'execute_center_of_native_safe_window')
        return finish('none', delay, best['window'], best['result'], 'approach_center_of_native_safe_window')
