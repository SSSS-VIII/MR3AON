"""Run recorded fixed-board inputs only after a visual identity/progress match."""
import bisect
import hashlib
import json
from pathlib import Path

from arena_fixed_match import Atlas, BoardTracker

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
    if target == 'jump1': return 'jump1'
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
        elif name in ('jump1','jump2'):
            jumps = int(name[-1])
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
                before=current, before_jumps=jumps, native_before=before['physics'],
                before_rope_height=(before['position']['y']-rope_y
                    if rope_y is not None and current in ('flip_up','flip_down')else None)))
    monotone = all(b['x'] >= a['x']-.05 for a,b in zip(poses,poses[1:]))
    clock_required = any(abs(b['x']-a['x'])<.2 and b['relative_tick']-a['relative_tick']>4
                         for a,b in zip(events,events[1:]))
    return dict(key=key, entry_x=poses[0]['x'], end_x=route['end']['state']['position']['x']-origin,
                poses=poses, events=events, native_passed=True, visual_execution_verified=False,
                monotone=monotone, requires_phase_clock=clock_required)


def compatible(expected, observation, jumps=None):
    actual = observation.get('phase', 'unknown')
    if expected == 'air':
        return actual.startswith('air_') and (jumps is None or observation.get('jumps')==jumps)
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
        return self.tracker.observe(pixels, observation)

    def event_lead(self, observation):
        cadence=observation.get('decision_interval_seconds',0.)
        if not 0 < cadence < .15:
            return .08
        velocity=getattr(self.tracker,'last_velocity',None)
        if velocity is None:
            return .08
        # A key submitted only after the boundary has been seen is on average
        # half a decision interval late. Android/Unity may consume it in either
        # of the next render frames; budget that one-frame uncertainty too.
        return max(.08,velocity*(cadence/2+1/60))

    def input_due(self,event,observation,x,visit=None):
        height=event.get('before_rope_height')
        player=observation.get('player')
        if (height is not None and observation.get('rope')is not None and hasattr(player,'center')
                and event['before']=='flip_up' and event['action']=='down' and abs(x-event['x'])<=1.5):
            actual=(observation['rope']-player.center[1])/observation.get('scale_px',39.5)
            cadence=observation.get('decision_interval_seconds',0.)
            # The short up/down combination must meet its original vertical
            # pose as well as its spatial neighborhood. Earlier first inputs
            # otherwise change the return height even at the same board X.
            return actual>=height-min(.3,max(0,cadence)*4)
        previous=self.last_fixed_commit
        if previous is not None and previous['visit']==(self.visit if visit is None else visit):
            prior=previous['event']
            ticks=event.get('relative_tick',-1000)-prior.get('relative_tick',0)
            if (event['index']==prior['index']+1 and event['before'] in ('flip_up','flip_down','air')
                    and 0 < ticks <= 11 and abs(x-event['x'])<=1.5):
                cadence=observation.get('decision_interval_seconds',0.)
                lead=min(.06,max(0,cadence)/2+1/60)
                return observation['time']+lead>=previous['time']+ticks*.02
        return x>=event['x']-self.event_lead(observation)

    def eligibility(self, observation):
        located = self.tracker.projected(observation)
        program = self.programs.get(located.get('key'))
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
        cursor = self.cursor if self.visit == visit else bisect.bisect_left(event_x,x-.65)
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
        if not pending:
            resume = bisect.bisect_left(event_x,x-.15)
            if self.visit != visit or poses[index]['phase'] in ('rope_above','rope_below','ground'):
                cursor = max(cursor,resume)
        located['cursor'] = cursor
        return program, located

    def uses_search(self, observation):
        program, _ = self.eligibility(observation)
        return not bool(program) and bool(getattr(self.reactive, 'uses_search', lambda _:False)(observation))

    def choose(self, observation):
        self.proposed_event = None
        self.proposed_primitive = None
        self.fixed_active = False
        program, located = self.eligibility(observation)
        self.decision = dict(mode='reactive', board=located)
        if program is not None:
            x = located['progress_x']
            events = program['events']
            visit = (located['key'], located['visit'])
            if self.visit != visit:
                # Joining mid-board is permitted only at the currently matched
                # native pose. Inputs behind that state must not be reissued.
                self.visit = visit
                self.cursor = located['cursor']
            else:
                self.cursor = max(self.cursor,located['cursor'])
            if self.cursor < len(events):
                event = events[self.cursor]
                if x > event['x']+.65:
                    self.decision['reason'] = 'missed_fixed_input_window'
                    return self.reactive.choose(observation)
                if self.input_due(event,observation,x):
                    if compatible(event['before'], observation,event.get('before_jumps')):
                        self.fixed_active = True
                        self.proposed_event = event
                        self.proposed_primitive = event['primitive']
                        self.decision.update(mode='fixed', event=event['index'])
                        return event['action'], 'fixed_route_'+event['primitive']
                    self.decision['reason'] = 'fixed_input_pose_mismatch'
                    return self.reactive.choose(observation)
            self.fixed_active = True
            self.decision['mode'] = 'fixed'
            return None, 'fixed_route_wait'
        return self.reactive.choose(observation)

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
    actor=HybridAvoider(reactive, bank, loaded['programs'])
    actor.runtime_assets={str(path):hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (bank.folder/'index.json',bank.folder/'features.npz')}
    actor.runtime_assets[str(programs)]=hashlib.sha256(program_bytes).hexdigest()
    return actor
