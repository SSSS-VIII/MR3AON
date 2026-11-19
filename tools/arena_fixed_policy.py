"""Run recorded fixed-board inputs only after a visual identity/progress match."""
import bisect
import hashlib
import json
from pathlib import Path

from arena_fixed_match import Atlas, BoardTracker,feature_signature
from arena_timing_certificate import valid as valid_timing_certificate, VERSION as TIMING_VERSION
from arena_input_transport import PROFILE as INPUT_TRANSPORT

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'arena/vision-fixed-routes.json'


def phase(native):
    name = native.split(':')[0].lower()
    if name == 'runonline': return 'rope_above'
    if name == 'runonlinedown': return 'rope_below'
    if name in ('runonground', 'slideonground'): return 'ground'
    if name in ('rolltolineon', 'airup'): return 'flip_up'
    if name in ('rolltolinedown', 'rolltoground'): return 'flip_down'
    if 'jump' in name or 'fall' in name: return 'air'
    return 'unknown'


def primitive(before, action, after):
    if action == 'down':
        return 'slide' if phase(before)=='ground' else 'rope_down' if phase(before)=='rope_above' else 'air_down'
    target = after.split(':')[0].lower()
    if target in ('jump','jump1'): return 'jump1'
    if target == 'jump2': return 'jump2'
    if phase(before) == 'rope_below': return 'rope_up'
    if phase(before) in ('flip_down', 'air'): return 'air_up'
    return 'jump1'


def compile_program(route, key):
    if not route.get('complete') or route.get('uses_restart_replay') is not False:
        raise ValueError('A fixed program needs a completed native snapshot search')
    origin = route['start']['board']['stage_start']
    poses, events = [], []
    jumps = 0
    rope_y = None
    for step in route['steps']:
        before, after = step['before'], step['after']
        if before['health'] != route['start']['health'] or after['health'] != before['health']:
            raise ValueError('A damaged native path cannot become a fixed program')
        current = phase(before['physics'])
        name = before['physics'].split(':')[0].lower()
        if current in ('rope_above','rope_below','ground'):
            jumps = 0
        elif name in ('jump','jump1','jump2'):
            # Original NinjaPhysicalState calls its first jump "jump: 14".
            # The following "fall: 15" must retain that consumed jump.
            jumps = 2 if name=='jump2'else 1
        if current in ('rope_above','rope_below'):
            rope_y=before['position']['y']-(.75 if current=='rope_above'else-.75)
        elif current=='ground':
            rope_y=None
        poses.append(dict(x=before['position']['x']-origin, phase=current, jumps=jumps))
        if step['action'] != 'none':
            effect = primitive(before['physics'], step['action'], after['physics'])
            events.append(dict(index=len(events), x=before['position']['x']-origin,
                action='slide' if effect=='slide' else step['action'], primitive=effect,
                relative_tick=step['relative_tick'],
                native_tick=before.get('episodeFrame'),
                before=current, before_jumps=jumps, native_before=before['physics'],
                before_rope_height=(before['position']['y']-rope_y
                    if rope_y is not None and current in ('flip_up','flip_down')else None)))
    monotone = all(b['x'] >= a['x']-.05 for a,b in zip(poses,poses[1:]))
    clock_required = any(abs(b['x']-a['x'])<.2 and b['relative_tick']-a['relative_tick']>4
                         for a,b in zip(events,events[1:]))
    certificate=route.get('timing_validation',{})
    robust=bool(certificate and valid_timing_certificate(certificate,
        route['start']['state']['episodeFrame'],route['end']['state']['episodeFrame'],len(events)))
    return dict(key=key, entry_x=poses[0]['x'], end_x=route['end']['state']['position']['x']-origin,
                poses=poses, events=events, native_passed=True, visual_execution_verified=False,
                monotone=monotone, requires_phase_clock=clock_required,
                input_order='Acknowledged event cursor; no automatic skipping after takeover',
                tick_seconds=.02,timing_robust=robust,timing_window_ms=80 if robust else None,
                timing_certificate_version=TIMING_VERSION if robust else None,
                input_transport=dict(INPUT_TRANSPORT)if robust else None,
                timing_evidence='finite_native_scenarios'if robust else None)


def compatible(expected, observation, jumps=None):
    actual = observation.get('phase', 'unknown')
    if expected == 'air':
        return actual.startswith(('air_','jump1_','jump2_')) and (jumps is None or observation.get('jumps')==jumps)
    return actual == expected


class HybridAvoider:
    def __init__(self, reactive, atlas, programs):
        self.reactive = reactive
        self.tracker = BoardTracker(atlas)
        self.programs = programs
        self.proposed_primitive = None
        self.proposed_event = None
        self.cursor = None
        self.visit = None
        self.fixed_active = False
        self.last_fixed_commit = None
        self.failed_visits = set()
        self.observed_contact = None
        self.decision = dict(mode='reactive', reason='no_visual_match')

    def __getattr__(self, name):
        return getattr(self.reactive, name)

    @property
    def last_action(self):
        return self.reactive.last_action

    @last_action.setter
    def last_action(self, value):
        self.reactive.last_action = value

    @property
    def revalidate_ground_down(self):
        return not self.fixed_active and getattr(self.reactive, 'revalidate_ground_down', False)

    def observe(self, pixels, observation):
        if observation.get('rope_contact_observed')and not observation.get('player_predicted'):
            self.observed_contact=dict(time=observation['time'],phase=observation['phase'])
        else:
            self.observed_contact=None
        # The next unacknowledged input bounds the spatial hypotheses. A
        # similar picture from a later repetition cannot advance this cursor.
        window=None
        if self.visit is not None and self.cursor is not None and self.visit not in self.failed_visits:
            program=self.programs.get(self.visit[0])
            if program is not None and self.cursor<len(program['events']):
                event=program['events'][self.cursor]
                previous=self.last_fixed_commit
                low=(previous['event']['x']-.8 if previous is not None
                     and previous['visit']==self.visit else program['entry_x']-.2)
                window=dict(key=self.visit[0],visit=self.visit[1],low=low,high=event['x']+.65,
                            event=event['index'],relative_tick=event.get('relative_tick'))
        self.tracker.action_window=window
        self.tracker.entry_windows={key:dict(low=p['entry_x']-.2,high=p['events'][0]['x']+.65)
            for key,p in self.programs.items()if p['events']and (self.visit is None or key!=self.visit[0])}
        return self.tracker.observe(pixels, observation)

    def begin_episode(self,*,level,slot):
        self.tracker.begin_episode(level=level,slot=slot)

    def warm(self,pixels,found):
        observation=dict(player=found[0],detections=found[1],
                         visible_supports=found[2]if len(found)>2 else [])
        return len(self.tracker.atlas.match(pixels,observation))

    def event_lead(self, observation):
        cadence=observation.get('decision_interval_seconds',0.)
        if not 0 < cadence < .15:
            return .08
        velocity=getattr(self.tracker,'last_velocity',None)
        if velocity is None:
            return .08
        # The observation is already projected to expected Unity consumption.
        # Center the discrete decision interval without adding that render
        # frame a second time; doing so systematically starts jumps early.
        return max(.08,velocity*cadence/2)

    def input_due(self,event,observation,x,visit=None):
        # Height/combination clocks are extra conditions, not permission to
        # move a recorded input ahead of the obstacle it was meant to clear.
        spatial_due=x>=event['x']-self.event_lead(observation)
        height=event.get('before_rope_height')
        player=observation.get('player')
        if (height is not None and observation.get('rope')is not None and hasattr(player,'center')
                and event['before']=='flip_up' and event['action']=='down' and abs(x-event['x'])<=1.5):
            actual=(observation['rope']-player.center[1])/observation.get('scale_px',39.5)
            cadence=observation.get('decision_interval_seconds',0.)
            # The short up/down combination must meet its original vertical
            # pose as well as its spatial neighborhood. Earlier first inputs
            # otherwise change the return height even at the same board X.
            return spatial_due and actual>=height-min(.3,max(0,cadence)*4)
        previous=self.last_fixed_commit
        if previous is not None and previous['visit']==(self.visit if visit is None else visit):
            prior=previous['event']
            ticks=event.get('relative_tick',-1000)-prior.get('relative_tick',0)
            if (event['index']==prior['index']+1 and event['before'] in ('flip_up','flip_down','air','rope_above','rope_below')
                    and 0 < ticks <= 60 and abs(x-event['x'])<=1.5):
                cadence=observation.get('decision_interval_seconds',0.)
                lead=min(.06,max(0,cadence)/2)
                return spatial_due and observation['time']+lead>=previous['time']+ticks*.02
        return spatial_due

    def eligibility(self, observation):
        located = self.tracker.projected(observation)
        program = self.programs.get(located.get('key'))
        certified = self.certified_positions(program,located,observation)
        if certified is not None:
            return program, certified
        if program and program.get('timing_robust'):
            return None, located
        if (not program or not program.get('monotone',True) or program.get('requires_phase_clock')
                or not located.get('localized') or observation.get('player') is None
                or observation.get('player_predicted')):
            return None, located
        x = located['progress_x']
        if x < program['entry_x']-.2 or x > program['end_x']+.15:
            return None, located
        poses = program['poses']
        index = max(0, bisect.bisect_right([p['x'] for p in poses], x)-1)
        events = program['events']
        event_x = [e['x'] for e in events]
        visit = (located['key'], located['visit'])
        cursor = self.cursor if self.visit == visit else 0
        event = events[cursor] if cursor < len(events) else None
        # A forecast can already be beyond the recorded input boundary before
        # this key has been sent. Compare its pre-input pose, not the future
        # post-input pose which this very submission is meant to produce.
        pending = (event is not None and self.input_due(event,observation,x,visit) and x <= event['x']+.65
                   and compatible(event['before'],observation,event.get('before_jumps')))
        if not pending:
            # Native poses are sampled on 40/60ms intervals, while the visual
            # action may already be between the poses on either side. A
            # nearby recorded transition is a valid continuation, not a reason
            # for the reactive actor to immediately undo the recorded key.
            lo=bisect.bisect_left([p['x'] for p in poses],x-.8)
            hi=bisect.bisect_right([p['x'] for p in poses],x+.8)
            if not any(compatible(p['phase'],observation,p.get('jumps'))
                       for p in poses[max(0,lo-1):max(hi,index+1)]):
                return None, located
        located['cursor'] = cursor
        return program, located

    def certified_positions(self, program, located, observation):
        """Localize an acknowledged tape; every submission still needs its pose.

        Finite endpoint evidence cannot authorize a jump with spent jumps or
        replace the current role's contact state with its nominal recorded pose.
        """
        if (not program or not program.get('timing_robust') or not program.get('monotone',True)
                or program.get('requires_phase_clock') or observation.get('player') is None
                or located.get('status')=='action_order_conflict'):
            return None
        visit = (located.get('key'),located.get('visit'))
        cursor = self.cursor if self.visit==visit else 0
        events = program['events']
        x = located.get('progress_x')
        if x is None or not program['entry_x']-.2 <= x <= program['end_x']+.15:
            return None
        if cursor:
            previous = self.last_fixed_commit
            if (previous is None or previous['visit'] != visit or previous['event']['index'] != cursor-1
                    or abs(self.last_action-previous['time']) > 1e-6):
                return None
        elif events and (x > events[0]['x']+.65
                        or not compatible(events[0]['before'],observation,events[0].get('before_jumps'))):
            return None
        predicted = observation.get('player_predicted')
        fresh_player = (not predicted or observation.get('player_prediction_reason') in ('short_gap','expected_above_view')
                        and 0 <= observation.get('player_seen_age',float('inf')) <= .35)
        std = located.get('progress_std',float('inf'))
        can_submit = located.get('localized') and std <= .25 and fresh_player
        # A weak odometer may justify waiting far before the next key; it may
        # never authorize a submission or silently skip that operation.
        can_wait = (cursor and cursor < len(events) and std <= 1
                    and x+3*std < events[cursor]['x']-self.event_lead(observation))
        if not can_submit and not can_wait:
            return None
        return dict(located,cursor=cursor,certified_positions=True,position_only_wait=not can_submit)

    def uses_search(self, observation):
        program, _ = self.eligibility(observation)
        return not bool(program) and bool(getattr(self.reactive, 'uses_search', lambda _:False)(observation))

    def synchronize(self,observation,located):
        """Rejoin a recorded resting pose using the existing safe flip model."""
        import arena_motion as motion
        program=self.programs.get(located.get('key'))
        actual=observation.get('phase')
        velocity=getattr(self.tracker,'last_velocity',None)
        risk=getattr(self.reactive,'_risk',None)
        if (not program or not program.get('monotone',True)or program.get('requires_phase_clock')
                or not located.get('localized')or located.get('progress_std',1)>.3
                or observation.get('player')is None or observation.get('player_predicted')
                or actual not in ('rope_above','rope_below')or observation.get('rope')is None
                or observation['time']-self.last_action<.25 or not velocity or velocity<=0 or risk is None):
            return None
        primitive='rope_up'if actual=='rope_below'else'rope_down'
        target='rope_above'if actual=='rope_below'else'rope_below'
        x=located['progress_x']
        finish=x+velocity*(motion.duration(primitive)+.1)
        if not program['entry_x']<=x<finish<=program['end_x']:
            return None
        if any(x-.15<=event['x']<=finish+1 for event in program['events']):
            return None
        poses=program['poses']
        at=bisect.bisect_right([p['x']for p in poses],finish)-1
        if at<0 or poses[at]['phase']!=target:
            return None
        cost,_,_=risk(observation,'flip')
        if cost!=0:
            return None
        self.proposed_primitive=primitive
        self.fixed_active=True
        self.decision.update(mode='synchronizing',reason='safe_recorded_rest_pose',target_phase=target)
        return ('jump'if primitive=='rope_up'else'down'),'fixed_entry_sync_'+primitive

    def hold_recorded_motion(self,observation,located):
        previous=self.last_fixed_commit
        risk=getattr(self.reactive,'_risk',None)
        if (previous is None or previous['visit']!=(located.get('key'),located.get('visit'))
                or observation.get('player')is None or risk is None):
            return False
        event=previous['event']
        jumps={'jump1':1,'jump2':2}.get(event['primitive'])
        elapsed=observation['time']-previous['time']
        if jumps is None or not 0<=elapsed<=.5 or not compatible('air',observation,jumps):
            return False
        program=self.programs.get(located.get('key'))
        if program is None or self.cursor is None:
            return False
        if self.cursor<len(program['events']):
            following=program['events'][self.cursor]
            due=previous['time']+(following['relative_tick']-event['relative_tick'])*.02
            if observation['time']+.1>=due:
                return False
        _,first,_=risk(observation,'none')
        if first<=.16:
            return False
        self.fixed_active=True
        self.decision.update(mode='recovering',reason='brief_place_uncertainty_after_own_jump')
        return True

    def short_combination(self,observation,located):
        """Complete only a recent own-input pair during brief place uncertainty."""
        previous=self.last_fixed_commit
        program=self.programs.get(located.get('key'))
        if (previous is None or previous['visit']!=(located.get('key'),located.get('visit'))
                or program is None or self.cursor is None or self.cursor>=len(program['events'])
                or observation.get('player')is None or observation.get('player_predicted')
                or located.get('progress_std',float('inf'))>.75 or located.get('progress_x')is None):
            return None
        event=program['events'][self.cursor]
        ticks=event['relative_tick']-previous['event']['relative_tick']
        elapsed=observation['time']-previous['time']
        x=located['progress_x']
        contact=self.observed_contact
        contact_pair=(previous['event']['primitive']in ('rope_down','rope_up','air_down','air_up')
                      and event['before']in ('rope_above','rope_below')and contact is not None
                      and contact['phase']==event['before']and 0<=observation['time']-contact['time']<=.15)
        if (event['index']!=previous['event']['index']+1 or not 0<ticks<=(60 if contact_pair else 11)
                or not 0<=elapsed<=ticks*.02+.08 or abs(x-event['x'])>1.5
                or event['before']not in ('flip_up','flip_down','air')and not contact_pair
                or not compatible(event['before'],observation,event.get('before_jumps'))):
            return None
        self.fixed_active=True
        self.decision.update(mode='recovering',reason='recent_own_input_pair')
        if not self.input_due(event,observation,x):
            return None,'fixed_route_short_combo_wait'
        self.proposed_event=event
        self.proposed_primitive=event['primitive']
        self.decision.update(mode='fixed',event=event['index'],short_pair=True)
        return event['action'],'fixed_route_'+event['primitive']

    def choose(self, observation):
        self.proposed_event = None
        self.proposed_primitive = None
        self.fixed_active = False
        program, located = self.eligibility(observation)
        self.decision = dict(mode='reactive', board=located)
        visit=(located.get('key'),located.get('visit'))
        if located.get('status')=='action_order_conflict':
            self.failed_visits.add(visit)
        if visit in self.failed_visits:
            self.decision['reason']='fixed_sequence_aborted'
            return self.reactive.choose(observation)
        if program is not None:
            x = located['progress_x']
            events = program['events']
            visit = (located['key'], located['visit'])
            if self.visit != visit:
                # Joining mid-board is permitted only at the currently matched
                # native pose. Inputs behind that state must not be reissued.
                self.visit = visit
                self.cursor = located['cursor']
            if self.cursor < len(events):
                event = events[self.cursor]
                if x > event['x']+.65:
                    self.failed_visits.add(visit)
                    self.decision['reason'] = 'missed_fixed_input_window'
                    return self.reactive.choose(observation)
                due = (x>=event['x']-self.event_lead(observation) if located.get('certified_positions')
                       else self.input_due(event,observation,x))
                if due:
                    if (not located.get('position_only_wait')and
                            compatible(event['before'], observation,event.get('before_jumps'))):
                        self.fixed_active = True
                        self.proposed_event = event
                        self.proposed_primitive = event['primitive']
                        self.decision.update(mode='fixed', event=event['index'])
                        return event['action'], 'fixed_route_'+event['primitive']
                    self.decision['reason'] = 'fixed_input_pose_mismatch'
                    self.fixed_active=True
                    return None,'fixed_route_wait_for_pose'
            self.fixed_active = True
            self.decision['mode'] = 'fixed'
            return None, 'fixed_route_wait'
        if self.programs.get(located.get('key'),{}).get('timing_robust'):
            self.decision['reason']='certified_tape_requires_visual_localization'
            return self.reactive.choose(observation)
        pair=self.short_combination(observation,located)
        if pair is not None:
            return pair
        if self.hold_recorded_motion(observation,located):
            return None,'fixed_route_relocalize_wait'
        sync=self.synchronize(observation,located)
        return sync if sync is not None else self.reactive.choose(observation)

    def on_commit(self, action, stamp):
        if self.proposed_event is not None and action == self.proposed_event['action']:
            self.last_fixed_commit=dict(event=self.proposed_event,time=stamp,visit=self.visit)
            self.cursor += 1
            self.proposed_event = None


def load(reactive, config=CONFIG, *, detector_sha256=None):
    config = Path(config)
    if not config.exists():
        return reactive
    value = json.loads(config.read_text())
    if value.get('schema') != 1:
        raise ValueError('Unknown fixed-route runtime configuration')
    atlas = ROOT / value['atlas']
    programs = ROOT / value['programs']
    if value.get('bundle')and (ROOT/value['bundle']).exists():
        bundle=(ROOT/value['bundle']).resolve()
        atlas,programs=bundle/'atlas',bundle/'programs.json'
    if not (atlas/'index.json').exists() or not programs.exists():
        return reactive
    programs=programs.resolve()
    program_bytes=programs.read_bytes()
    loaded = json.loads(program_bytes)
    if loaded.get('schema') != 1:
        raise ValueError('Unknown fixed input library schema')
    bank = Atlas(atlas)
    if detector_sha256 is None or bank.meta.get('detector_sha256') != detector_sha256:
        return reactive
    if bank.meta.get('feature_sha256')!=feature_signature():
        return reactive
    # Old counter-clock certificates and nominal-only routes are retained as
    # research artifacts, not silently admitted into the new runtime bank.
    programs_validated={key:p for key,p in loaded['programs'].items()
        if p.get('timing_robust')and p.get('timing_certificate_version')==TIMING_VERSION
        and p.get('input_transport')==INPUT_TRANSPORT}
    actor=HybridAvoider(reactive, bank, programs_validated)
    actor.runtime_assets={str(path):hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (bank.folder/'index.json',bank.folder/'features.npz')}
    actor.runtime_assets[str(programs)]=hashlib.sha256(program_bytes).hexdigest()
    return actor
