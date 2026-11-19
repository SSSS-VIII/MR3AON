"""Revalidate a visual-entry adjustment from a retained whole-VM checkpoint.

This is a new forward candidate, not an undo by replay. Later input boundaries
stay at their original frames and world X; every tolerance test runs again.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

from arena_fixed_goal import exit_kind
from arena_timing_certificate import valid
from search import BOARD
from timing_margin import verify


def plan(report, event_index, shift_ticks):
    rows = deepcopy(report['route'])
    keys = [i for i, row in enumerate(rows) if row['action'] != 'none']
    if (not report.get('complete') or report.get('uses_restart_replay') is not False or not valid(report.get('timing_validation', {}),
            report['start']['state']['episodeFrame'], report['end']['state']['episodeFrame'], len(keys))):
        raise ValueError('Retiming requires a certified complete source')
    if type(shift_ticks) is not int or not shift_ticks:
        raise ValueError('Use a nonzero integer tick adjustment')
    if not 0 <= event_index < len(keys):
        raise ValueError('Unknown input index')
    old = keys[event_index]
    target = rows[old]['job']['before']['episodeFrame'] + shift_ticks
    new = next((i for i, row in enumerate(rows) if row['job']['before']['episodeFrame'] == target), None)
    if new is None:
        raise ValueError('Adjusted input must land on a retained interval boundary')
    if (event_index and new <= keys[event_index-1] or
            event_index+1 < len(keys) and new >= keys[event_index+1]):
        raise ValueError('Adjustment changes input order')
    action = rows[old]['action']
    rows[old]['action'] = 'none'
    rows[new]['action'] = action
    return rows


def run(gate, source, output, *, event_index, shift_ticks, collector=None):
    source, output = Path(source), Path(output)
    raw = source.read_bytes()
    original = json.loads(raw)
    planned = plan(original, event_index, shift_ticks)
    root = original['initial_ram_root']['result']['id']
    if root not in gate.points:
        raise ValueError('The original VM checkpoint is no longer retained')
    output.mkdir(parents=True, exist_ok=False)
    report = dict(schema=1, complete=False, native_decision=True,
        uses_restart_replay=False, no_health_loss=False, start=original['start'], route=[],
        algorithm='Retimed forward candidate with full independent native timing revalidation',
        retimed_from=dict(path=str(source), sha256=hashlib.sha256(raw).hexdigest(),
                          event=event_index, shift_ticks=shift_ticks),
        initial_ram_root=original['initial_ram_root'])
    (output/'retime-source.py').write_bytes(Path(__file__).read_bytes())
    owned = set(gate.points)
    park = gate.snapshot()['result']['id']
    began = time.monotonic()
    try:
        gate.restore(root)
        state = gate.call('state')
        if state != original['start']['state'] or gate.call('exec', code=BOARD) != original['start']['board']:
            raise RuntimeError('Retained VM entry does not match the certified source')
        if collector is not None:
            collector.begin(gate, root, original['start'])
        for i, row in enumerate(planned):
            if (row['action'] != 'none' and row['action'] == original['route'][i]['action']
                    and abs(state['position']['x']-row['job']['before']['position']['x']) > .02):
                raise RuntimeError('A later input moved away from its independent world-X target')
            job = gate.step(row['ticks'], row['action'])
            state = job['after']
            board = gate.call('exec', code=BOARD)
            if (job.get('terminated') or job.get('error') or state['health'] != original['start']['health']):
                report['failure'] = dict(row=i, job=job)
                return report
            point = gate.snapshot()['result']['id']
            report['route'].append(dict(action=row['action'], ticks=row['ticks'], job=job, board=board, point=point))
            if collector is not None and (row['action'] != 'none' or i % 12 == 0):
                collector.capture(gate, point, original['start']['board'])
            crossed = exit_kind(original['start']['board'], board)
            if crossed:
                break
        report['end'] = dict(state=state, board=board)
        report['no_health_loss'] = True
        if not crossed:
            report['failure'] = dict(reason='Adjusted candidate did not reach the native exit')
            return report
        with (output/'timing-validation.jsonl').open('w') as stream:
            def progress(check):
                stream.write(json.dumps(check)+'\n'); stream.flush()
                print(f'视觉入口整板验证: 操作{check["event"]} 偏移{check["shift_ms"]}ms 通过={check["passed"]}', flush=True)
            report['timing_validation'] = verify(gate, report['route'], initial_point=root,
                initial_state=original['start']['state'], start=original['start'], board_code=BOARD,
                whole_board=True, on_result=progress)
        report['complete'] = valid(report['timing_validation'],report['start']['state']['episodeFrame'],
            report['end']['state']['episodeFrame'],sum(r['action']!='none'for r in report['route']))
        if report['timing_validation']['passed']and not report['complete']:
            report['failure']=dict(reason='fresh_entry_validation_required')
        if report['complete']:
            report['exit_kind'] = crossed
        if collector is not None:
            report['references'] = collector.status()
        return report
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        report['seconds'] = time.monotonic()-began
        try:
            gate.restore(park)
            for point in set(gate.points)-owned:
                gate.drop(point)
        except BaseException as error:
            # An uncertain restore must retain its recovery points.
            report['owner_restore_error'] = repr(error)
            raise
        finally:
            for row in report['route']:
                row.pop('point', None)
            (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
