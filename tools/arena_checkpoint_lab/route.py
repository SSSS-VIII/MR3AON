"""Export only contiguous committed native steps, never rejected trial inputs."""
import hashlib
import json
from pathlib import Path


def export(reports, destination):
    if not reports:
        raise ValueError('At least one native search report is required')
    sources = []
    result = dict(schema=1, complete=False, entry_prefix_covered=False,
                  scope='Recorded native starting state through the next grounded board',
                  trap_context_available=False, visual_execution_validated=False,
                  uses_restart_replay=False, sources=sources, steps=[])
    expected = None
    board = None
    for path in map(Path, reports):
        raw = path.read_bytes()
        report = json.loads(raw)
        if report.get('uses_restart_replay') is not False or not report.get('route'):
            raise ValueError('A source must contain committed native steps without restart/replay')
        start = report['start']
        if expected is None:
            result['start'] = start
            expected = start['state']
            board = start['board']
        elif start['state'] != expected or start['board'] != board:
            raise ValueError('Native states or board contexts do not match at the report seam')
        if result['complete']:
            raise ValueError('A route already reached its board exit')
        for row in report['route']:
            job = row['job']
            before, after = job['before'], job['after']
            ticks = row['ticks']
            if (row['action'] not in ('none', 'jump', 'down') or ticks not in (2, 3)
                    or job.get('terminated') or job.get('error') or not job.get('done')
                    or before != expected or after['episodeFrame'] - before['episodeFrame'] != ticks
                    or before['health'] != result['start']['health'] or after['health'] != before['health']):
                raise ValueError('A source contains a discontinuous, unfinished or damaged native interval')
            if board['map'] != result['start']['board']['map'] or board['mounted']:
                raise ValueError('Native route changed map or mount context')
            result['steps'].append(dict(action=row['action'], ticks=ticks,
                relative_tick=before['episodeFrame'] - result['start']['state']['episodeFrame'],
                local_x=before['position']['x'] - board['stage_start'],
                stage_id=board['stage_id'], stage_index=board['stage_index'],
                physics_before=before['physics'], physics_after=after['physics'],
                before=before, after=after))
            expected = after
            board = row['board']
            if board['map'] != result['start']['board']['map'] or board['mounted']:
                raise ValueError('Native route left its original unmounted map context')
        if report.get('complete'):
            if (board['stage_index'] <= result['start']['board']['stage_index']
                    or report['end']['state'] != expected or report['end']['board'] != board):
                raise ValueError('Completed report does not actually reach the next native board')
            result['complete'] = True
        sources.append(dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
                            first_tick=start['state']['episodeFrame'], last_tick=expected['episodeFrame']))
    result['end'] = dict(state=expected, board=board)
    result['duration_ticks'] = expected['episodeFrame'] - result['start']['state']['episodeFrame']
    result['action_events'] = [{key: row[key] for key in ('action', 'relative_tick', 'local_x',
                                'stage_id', 'stage_index', 'physics_before', 'physics_after')}
                              for row in result['steps'] if row['action'] != 'none']
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('Keep previous route artifacts instead of overwriting them')
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result
