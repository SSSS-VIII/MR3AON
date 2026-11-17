"""Commit own submitted keys using the Android enqueue acknowledgement clock."""
from collections import deque
import math
from arena_vision import extrapolate


def selected_primitive(action,reason):
    """Carry the chosen primitive separately from the shared input key."""
    expected={'air_up':'jump','rope_up':'jump','jump1':'jump','jump2':'jump',
              'air_down':'down','rope_down':'down','slide':'slide'}
    name=(reason.removeprefix('mpc_')if reason.startswith('mpc_')else
          'air_down'if reason.startswith('air_down:')else None)
    return name if expected.get(name)==action else None


def commit_action(perception,latest,action,ack,input_delay=1/60,*,primitive=None,planned=None):
    """Enqueue is observed; Unity consumption remains a render-frame prior.

    The planner's future timestamp includes a compute-time estimate. Once the
    key has actually been submitted that estimate must not remain the action
    origin, nor may a privileged Unity receipt supply the replacement clock.
    """
    enqueued=ack.device_ready_ns/1e9
    stamp=enqueued+input_delay
    timeline=getattr(perception,'input_timeline',None)
    if timeline is not None:
        current=timeline.project(stamp,include_tracks=False)
        timeline.record(action,ack,primitive=primitive,planned=planned or latest,input_delay=input_delay)
        committed=timeline.project(stamp,include_tracks=False)
        active=committed.get('motion')or{}
        return dict(enqueued_time=enqueued,committed_time=stamp,
                    committed_phase=current['phase'],committed_jumps=current['jumps'],
                    submitted_primitive=primitive,committed_primitive=active.get('name'),
                    support_unconfirmed=bool(active.get('support_unconfirmed')))
    current=extrapolate(latest,stamp)
    if primitive is None:
        perception.action(action,stamp,current)
    else:
        perception.action(action,stamp,current,primitive=primitive,source_observation=planned or latest)
    return dict(enqueued_time=enqueued,committed_time=stamp,
                committed_phase=current['phase'],committed_jumps=current['jumps'],
                submitted_primitive=primitive,
                committed_primitive=(perception.active_motion or{}).get('name'),
                support_unconfirmed=bool((perception.active_motion or{}).get('support_unconfirmed')))


class DecisionCadence:
    """Past host decision intervals, independent of game state and image labels."""
    def __init__(self):
        self.previous=None
        self.intervals=deque(maxlen=32)

    def observe(self,stamp):
        if isinstance(stamp,bool) or not math.isfinite(stamp):
            raise ValueError('Decision timestamp must be finite')
        if self.previous is not None:
            interval=stamp-self.previous
            if interval<=0:raise ValueError('Decision timestamps must increase')
            self.intervals.append(interval)
        self.previous=stamp
        if len(self.intervals)<3:return 0.
        ordered=sorted(self.intervals)
        index=.9*(len(ordered)-1);lo=int(index);fraction=index-lo
        return ordered[lo]+fraction*(ordered[min(lo+1,len(ordered)-1)]-ordered[lo])
