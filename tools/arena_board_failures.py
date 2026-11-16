#!/usr/bin/env python3
"""Audit saved actor health events and board boundaries, without a client or GPU.

Native telemetry is offline evidence only. A retained enemy reference is not a
proven damage cause; episode damage is never divided between observed boards.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
import hashlib
import json
import math
from pathlib import Path
from arena_key_receipts import KeyReceiptMatcher


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def health_events(row,origin):
    """Read bounded native event history and the legacy sticky witness."""
    result=[];invalid=[];ring=row.get('health_drops')
    if isinstance(ring,dict)and set(ring)=={str(i+1)for i in range(len(ring))}:
        ring=[ring[str(i+1)]for i in range(len(ring))]
    if ring is not None:
        if isinstance(ring,list):
            result.extend((event,f'{origin}.health_drops[{i}]')for i,event in enumerate(ring,1))
        else:invalid.append(origin+'.health_drops')
    if row.get('last_health_drop')is not None:result.append((row['last_health_drop'],origin))
    return result,invalid


def read_rows(path):
    rows = []
    for line, text in enumerate(path.read_text().splitlines(), 1):
        if not text.strip():
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f'{path}:{line}: invalid JSON') from exc
        if not isinstance(row, dict):
            raise ValueError(f'{path}:{line}: expected an object')
        rows.append(row)
    return rows


def board(row):
    values = [row.get(key) for key in ('map', 'stageIndex', 'stageID')]
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return None
    if values[0] <= 0 or values[1] < 0 or values[2] <= 0:
        return None
    return dict(native_map=values[0], native_stage_index=values[1], stage_id=values[2])


def board_key(value):
    return tuple(value.values())


def sample_context(sample):
    row = sample['row']
    return dict(monotonic=row['monotonic'], board=board(row), physics=row.get('physics'),
                native_stage={key: row.get(key) for key in ('map', 'stageIndex', 'stageID')},
                damage=row.get('damage'), health=row.get('health'), origin=sample['origin'])


def locate_board(stamp, samples):
    """Use both surrounding samples, never the stage of a later sticky event."""
    index = bisect_left([sample['row']['monotonic'] for sample in samples], stamp)
    before = samples[index-1] if index else None
    after = samples[index] if index < len(samples) else None
    a, b = board(before['row']) if before else None, board(after['row']) if after else None
    candidates = list({board_key(value): value for value in (a, b) if value}.values())
    # A boss map can initially expose stageID=0. The visible map transition is
    # still a boundary even though its new board cannot yet be identified.
    crossed = False
    if before and after:
        for key, minimum in (('map', 1), ('stageIndex', 0), ('stageID', 1)):
            old, new = before['row'].get(key), after['row'].get(key)
            if number(old) and number(new) and min(old, new) >= minimum and old != new:
                crossed = True
    status = ('attributed' if a and a == b else
              'boundary_ambiguous' if crossed else 'unresolved')
    return dict(status=status, board=a if status == 'attributed' else None,
                candidates=candidates, before=sample_context(before) if before else None,
                after=sample_context(after) if after else None,
                bracket_ms=(after['row']['monotonic']-before['row']['monotonic'])*1000
                if before and after else None,
                scope='Observed native stage bracket, not an exact transition timestamp')


def capture_stamp(row):
    # Actor rows contain an extrapolated decision state, not the raw capture state.
    stamp, age = row.get('time'), row.get('observation_age_ms')
    if number(stamp) and number(age) and age >= 0:
        return stamp-age/1000
    return None  # Do not silently align legacy/unknown clocks or host elapsed time.


def visual_context(row, folder, stamp):
    captured = capture_stamp(row)
    frame = row.get('frame')
    paths = {}
    if isinstance(frame, int) and not isinstance(frame, bool) and frame >= 0:
        for key, suffix in (('raw', '.png'), ('overlay', '-overlay.jpg')):
            path = folder/f'{frame:06d}{suffix}'
            paths[key] = str(path) if path.is_file() else None
    return dict(frame=frame, capture_monotonic=captured, decision_monotonic=row['time'],
                alignment_ms=(captured-stamp)*1000, observation_age_ms=row['observation_age_ms'],
                phase_at_decision=row.get('phase'), jumps_at_decision=row.get('jumps'),
                action=row.get('action'), reason=row.get('reason'), images=paths,
                scope='Image clock from decision time minus observation age; phase is still predicted at decision')


def visuals_at_hit(stamp, vision, folder):
    candidates = [row for row in vision if capture_stamp(row) is not None]
    saved = [row for row in candidates if isinstance(row.get('frame'), int) and not isinstance(row['frame'], bool)
             and (folder/f"{row['frame']:06d}.png").is_file()]
    preceding = [row for row in saved if capture_stamp(row) <= stamp]

    def context(rows, *, previous=False):
        if not rows:
            return None
        row = max(rows, key=capture_stamp) if previous else min(rows, key=lambda r: abs(capture_stamp(r)-stamp))
        return visual_context(row, folder, stamp)

    return dict(nearest_observation=context(candidates), nearest_saved_image=context(saved),
                preceding_saved_image=context(preceding, previous=True),
                unknown_capture_clock_rows=len(vision)-len(candidates))


def action_timeline(actions, samples):
    clocks=[sample['row']['monotonic']for sample in samples if number(sample['row'].get('monotonic'))]
    clocks += [a['enqueued_time']for a in actions if isinstance(a,dict)and number(a.get('enqueued_time'))]
    matcher=KeyReceiptMatcher(min(clocks)-1 if clocks else 0)
    receipts = {}
    for sample in samples:
        for key, receipt in (sample['row'].get('keyReceipts') or {}).items():
            if isinstance(receipt, dict) and number(receipt.get('time')):
                event,_=matcher.match(key,receipt,actions)
                if event is not None:receipts[id(event)] = receipt['time']
    result, unknown = [], []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError('actor actions must be objects')
        stamp = receipts.get(id(action))
        clock = 'native_key_receipt'
        if stamp is None:
            committed, error = action.get('committed_time'), action.get('committed_anchor_error_ms')
            if number(action.get('enqueued_time')):
                stamp, clock = action['enqueued_time'], 'enqueued_time_no_native_receipt'
            elif number(committed) and number(error):
                stamp, clock = committed-error/1000, 'native_receipt_from_anchor_error'
            else:
                # request_ns is a HOST clock; it cannot substitute for native time.
                unknown.append(index)
                continue
        keys = ('action', 'reason', 'key', 'key_count', 'submitted_primitive', 'committed_primitive',
                'committed_phase', 'committed_jumps', 'committed_time', 'planned_time', 'enqueued_time',
                'capture_to_unity_ms', 'support_unconfirmed')
        result.append(dict(index=index, monotonic=stamp, clock=clock,
                           **{key: action[key] for key in keys if key in action}))
    return sorted(result, key=lambda action: action['monotonic']), unknown


def actions_at_hit(stamp, timeline):
    previous = [action for action in timeline if action['monotonic'] <= stamp]
    following = [action for action in timeline if action['monotonic'] > stamp]

    def relative(action):
        return dict(action, relative_ms=(action['monotonic']-stamp)*1000) if action else None

    return dict(previous=relative(previous[-1] if previous else None),
                preceding_600ms=[relative(action) for action in previous if action['monotonic'] >= stamp-.6],
                next=relative(following[0] if following else None))


def audit_run(folder):
    folder = Path(folder).resolve()
    files = {name: folder/name for name in ('setup.json', 'report.json', 'evaluation.jsonl', 'vision.jsonl')}
    setup, report = (json.loads(files[name].read_text()) for name in ('setup.json', 'report.json'))
    if not isinstance(setup, dict) or not isinstance(report, dict):
        raise ValueError('not an actor report')
    if setup.get('observe'):
        raise ValueError('observe-only collection is not an actor run')
    if (not isinstance(setup.get('initial'), dict) or not isinstance(report.get('final'), dict)
            or not isinstance(report.get('actions'), list) or not isinstance(report.get('board_entries'), list)
            or not isinstance(report.get('status'), str)):
        raise ValueError('not an actor report: missing initial/final/actions/board_entries/status')
    evaluation, vision = (read_rows(files[name]) for name in ('evaluation.jsonl', 'vision.jsonl'))
    initial, final = setup['initial'], report['final']
    begin, end = initial.get('monotonic'), final.get('monotonic')
    if not number(begin) or not number(end) or end < begin:
        raise ValueError('actor native time range is missing or invalid')
    # Initial/final can bridge first/last polls, but preserve their provenance.
    samples = [dict(row=initial, origin='setup.initial')]
    samples += [dict(row=row, origin=f'evaluation.jsonl:{i}') for i, row in enumerate(evaluation, 1)
                if number(row.get('monotonic')) and begin <= row['monotonic'] <= end]
    samples.append(dict(row=final, origin='report.final'))
    samples.sort(key=lambda sample: sample['row']['monotonic'])

    unique, invalid_events = {}, []
    for sample in samples:
        events,invalid=health_events(sample['row'],sample['origin']);invalid_events.extend(invalid)
        for event,origin in events:
            if not isinstance(event, dict) or not all(number(event.get(key)) for key in ('monotonic', 'before', 'after')):
                invalid_events.append(origin)
                continue
            if event['before'] <= event['after']:
                invalid_events.append(origin)
                continue
            identity = (event['monotonic'], event.get('frame'), event['before'], event['after'])
            entry = unique.setdefault(identity, dict(native=event, references=[]))
            entry['references'].append(origin)
    excluded, hits = [], []
    timeline, unknown_actions = action_timeline(report['actions'], samples)
    for identity, entry in sorted(unique.items(), key=lambda item: item[0][0]):
        event, stamp = entry['native'], identity[0]
        if not begin < stamp <= end:
            excluded.append(dict(event=event, reason='outside_actor_native_time_range', references=entry['references']))
            continue
        hits.append(dict(event_index=len(hits), monotonic=stamp, elapsed_from_initial=stamp-begin,
                         health_loss=event['before']-event['after'], native_event=event,
                         first_reference=entry['references'][0], reference_count=len(entry['references']),
                         board_assignment=locate_board(stamp, samples),
                         visual=visuals_at_hit(stamp, vision, folder), actions=actions_at_hit(stamp, timeline)))

    boards = {}
    for sample in samples:
        value = board(sample['row'])
        if value is None:
            continue
        item = boards.setdefault(board_key(value), dict(board=value, first_observed=sample['row']['monotonic'],
                                last_observed=sample['row']['monotonic'], witnessed_attributed_loss=0,
                                event_indices=[], ambiguous_event_indices=[]))
        item['last_observed'] = sample['row']['monotonic']
    unassigned_loss = 0
    for hit in hits:
        assignment = hit['board_assignment']
        if assignment['status'] == 'attributed':
            item = boards[board_key(assignment['board'])]
            item['witnessed_attributed_loss'] += hit['health_loss']
            item['event_indices'].append(hit['event_index'])
        else:
            unassigned_loss += hit['health_loss']
            for candidate in assignment['candidates']:
                boards[board_key(candidate)]['ambiguous_event_indices'].append(hit['event_index'])

    baseline = initial.get('damage', 0)
    total = final.get('damage')
    if not number(baseline) or not number(total) or total < baseline:
        raise ValueError('invalid native cumulative damage range')
    counters = [sample['row']['damage'] for sample in samples if number(sample['row'].get('damage'))]
    witnessed = sum(hit['health_loss'] for hit in hits)
    damage = total-baseline
    return dict(run=str(folder), status=report['status'], seed=setup.get('seed'), level=setup.get('level'),
                requested=dict(map=setup.get('map'), start=setup.get('start'), pins=setup.get('pins'),
                               goal_stage_index=setup.get('goal_stage_index'), boards=report.get('boards_requested')),
                reported_board_entries=report['board_entries'],
                native_time_range=[begin, end], hits=hits, boards=list(boards.values()),
                damage=dict(initial_counter=baseline, final_counter=total, episode=damage,
                            witnessed_event_loss=witnessed, witnessed_unassigned_loss=unassigned_loss,
                            unwitnessed_loss=max(0, damage-witnessed), events_exceed_counter=max(0, witnessed-damage),
                            counter_monotonic=all(a <= b for a, b in zip(counters, counters[1:]))),
                evidence=dict(evaluation_rows=len(evaluation), vision_rows=len(vision),
                              excluded_events=excluded, invalid_event_origins=invalid_events,
                              actions_without_native_clock=unknown_actions,
                              god_mode_observed=any(sample['row'].get('god') is True for sample in samples),
                              evaluation_error=report.get('evaluation_error')),
                input_sha256={name: digest(path) for name, path in files.items()},
                actor_sources_recorded=setup.get('sources'), detector_recorded=setup.get('detector'),
                scope=['Offline saved actor evidence; no policy, device or GPU access',
                       'Board indices and maps are original native values, not menu slot numbers',
                       'Board loss is only witnessed attributed loss; zero is not a no-hit acceptance',
                       'Cumulative damage may include events overwritten between evaluation polls',
                       'Retained enemy references may be stale; post-hit geometry may already include hurt response'])


def build_audit(folders):
    runs, errors = [], []
    for folder in dict.fromkeys(str(Path(folder).resolve()) for folder in folders):
        try:
            runs.append(audit_run(folder))
        except (OSError, ValueError, TypeError) as exc:
            errors.append(dict(run=folder, error=str(exc)))
    return dict(schema=1, tool_sha256=digest(Path(__file__)), runs=runs, errors=errors,
                summary=dict(runs=len(runs), errors=len(errors), events=sum(len(run['hits']) for run in runs),
                             episode_damage=sum(run['damage']['episode'] for run in runs),
                             unwitnessed_loss=sum(run['damage']['unwitnessed_loss'] for run in runs),
                             unassigned_event_loss=sum(run['damage']['witnessed_unassigned_loss'] for run in runs)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', type=Path, nargs='+', help='Saved actor directories, read only')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build_audit(args.runs)
    # Refuse accidental overwrite of a saved report or a previous audit.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps(result['summary'], ensure_ascii=False))
    return bool(result['errors'])


if __name__ == '__main__':
    raise SystemExit(main())
