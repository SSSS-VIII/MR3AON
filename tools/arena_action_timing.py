"""Commit own submitted keys using the Android enqueue acknowledgement clock."""
from arena_vision import extrapolate


def commit_action(perception,latest,action,ack,input_delay=1/60):
    """Enqueue is observed; Unity consumption remains a render-frame prior.

    The planner's future timestamp includes a compute-time estimate. Once the
    key has actually been submitted that estimate must not remain the action
    origin, nor may a privileged Unity receipt supply the replacement clock.
    """
    enqueued=ack.device_ready_ns/1e9
    stamp=enqueued+input_delay
    current=extrapolate(latest,stamp)
    perception.action(action,stamp,current)
    return dict(enqueued_time=enqueued,committed_time=stamp,
                committed_phase=current['phase'],committed_jumps=current['jumps'])
