"""Check finite-ground down targets using only pixels and own input clocks."""
import math
from arena_vision import ground_down_target, can_air_down

FRAME = 1 / 60


def needs_ground_down_check(action, primitive, planned):
    return (action == 'down' and primitive == 'air_down'
            and planned.get('rope') is None
            and (planned.get('terrain') or {}).get('source') == 'neural_segments')


def ground_down_commit_check(project, send_stamp):
    """Sample the same landing top over zero to two original render frames.

    This is a sampled timing check, not a bound on every transport delay or a
    proof that the entire trajectory is collision free. The projector must
    replay own keys without confirming predicted contacts.
    """
    if not math.isfinite(send_stamp):
        raise ValueError('Finite submission time required')
    samples = []
    for delay in (0., FRAME, 2 * FRAME):
        stamp = send_stamp + delay
        state = project(stamp)
        target = None
        if (state.get('player') is not None and state.get('rope') is None
                and (state.get('terrain') or {}).get('source') == 'neural_segments'
                and can_air_down(state)):
            target = ground_down_target(state)
        samples.append(dict(stamp=stamp, delay=delay, phase=state.get('phase'),
                            observation_age_ms=state.get('observation_age_ms'),
                            surface_id=target.get('surface_id') if target else None,
                            contact_seconds=target.get('contact_seconds') if target else None))
    available = all(row['surface_id'] is not None for row in samples)
    same = available and len({row['surface_id'] for row in samples}) == 1
    reason = ('same_visible_ground_target' if same else
              'ground_down_target_unavailable' if not available else
              'ground_down_target_changes')
    return dict(allowed=bool(same), reason=reason, samples=samples)


def validate_ground_down(policy, action, primitive, planned, project,
                         send_stamp, last_action_before):
    """Cancel an unconfirmed down without claiming its key was submitted."""
    if not needs_ground_down_check(action, primitive, planned):
        return action, None
    result = (ground_down_commit_check(project, send_stamp) if project is not None else
              dict(allowed=False, reason='no_own_input_timeline', samples=[]))
    if not result['allowed']:
        # Air-down has no other chooser follow-up side effect to roll back.
        policy.last_action = last_action_before
        return None, result
    return action, result
