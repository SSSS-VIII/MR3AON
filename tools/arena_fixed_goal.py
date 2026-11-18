"""Finite native exit witnesses for ordinary, boss and repeating loop boards."""


def exit_kind(before, after):
    if after.get('stage_index', -1) < 0:
        return None
    if after['map'] != before['map']:
        count = before.get('stage_count')
        return ('map_advance' if count is not None and before['stage_index'] == count - 1 else None)
    if after['stage_index'] > before['stage_index']:
        return 'stage_advance'
    if (before.get('loop') and after.get('loop')
            and before.get('instance') is not None and after.get('instance') is not None
            and before['instance'] != after['instance']
            and after.get('stage_start', 0) > before.get('stage_start', 0) + .01):
        return 'loop_advance'
    return None
