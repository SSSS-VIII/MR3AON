"""Commit own submitted keys using the Android enqueue acknowledgement clock."""
from arena_vision import extrapolate


def selected_primitive(action,reason):
    """Carry the chosen MPC primitive separately from the shared input key."""
    expected={'air_up':'jump','rope_up':'jump','jump1':'jump','jump2':'jump',
              'air_down':'down','rope_down':'down','slide':'slide'}
    name=reason.removeprefix('mpc_')if reason.startswith('mpc_')else None
    return name if expected.get(name)==action else None


def commit_action(perception,latest,action,ack,input_delay=1/60,*,primitive=None,planned=None):
    """Enqueue is observed; Unity consumption remains a render-frame prior.

    The planner's future timestamp includes a compute-time estimate. Once the
    key has actually been submitted that estimate must not remain the action
    origin, nor may a privileged Unity receipt supply the replacement clock.
    """
    enqueued=ack.device_ready_ns/1e9
    stamp=enqueued+input_delay
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
