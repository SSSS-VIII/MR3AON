#!/usr/bin/env python3
"""Bounded standalone internal-controller evaluation on the named local arena.

No stored route, vision actor, native action search, snapshot or injury rollback
is involved. A fresh selection starts an independent test, never an undo.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np

from arena_local import LocalClient, ROOT
from arena_bootstrap import wait_job
from arena_privileged_model import PlayerModel, hazard_forecasts, rows
from arena_privileged_policy import InternalController
from runtime import InstanceSession


def json_safe(value):
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class Held(LocalClient):
    def execute(self, *args, **kwargs):
        return super().execute(*args, **dict(kwargs, lease_held=True))


def install(client):
    for path in (ROOT/'tools/arena_privileged_state.lua', ROOT/'tools/arena_checkpoint_lab/clock_step.lua'):
        client.execute('assert(load('+json.dumps(path.read_text())+'))();return true')


def observe(client):
    return client.execute('return MR3A.privileged_state()')


def interval(client, frames, action):
    client.execute('MR3A.privileged_job=MR3A.advance_render('+str(frames)+','+json.dumps(action)+');return true')
    return wait_job(client, 'MR3A.privileged_job', timeout=10)


def select(client, *, seed, level, map_id, board):
    specification = dict(level=level, map=map_id, start=1, pins={'1':board})
    client.execute('return MR3A.native_select(json.parse('+json.dumps(json.dumps(specification))+'),'+str(seed)+')')
    wait_job(client, 'MR3A.travel', timeout=610)
    client.execute('MR3A.menu_suppressed=true;MR3A.hide_menu();return true')


def forecast_error(before, after, action):
    elapsed = after['state']['time']-before['state']['time']
    times = np.linspace(0., elapsed, max(2, round(elapsed*120)+1))
    model = PlayerModel(before)
    bodies, motors, valid = model.trajectory(times, () if action == 'none' else ((0., action),))
    body = rows(after['role']['colliders'])[0]
    result = dict(seconds=elapsed, player_error_m={
        'x':float(bodies[-1, 0]-body['center']['x']),
        'y':float(bodies[-1, 1]-body['center']['y'])}, valid=valid,
        predicted_mode=motors[-1].mode, actual_mode=after['state']['physics'], enemies=[])
    forecasts, missing = hazard_forecasts(before, times, model)
    actual = {c['id']:c for e in rows(after['enemies']) for c in rows(e['colliders'])}
    for h in forecasts:
        if h.id not in actual:
            continue
        c = actual[h.id]
        result['enemies'].append(dict(id=h.id, type=h.kind,
            predicted_active=bool(h.active[-1]), actual_active=c['active'] and c['enabled'],
            error_x=float(h.centers[-1, 0]-c['center']['x']),
            error_y=float(h.centers[-1, 1]-c['center']['y']), approximate=h.approximate))
    result['unsupported'] = missing
    return result


def evaluate(client, output, *, seconds=30., coast=False):
    output.mkdir(parents=True, exist_ok=False)
    source_files = ['arena_privileged_state.lua', 'arena_privileged_model.py',
                    'arena_privileged_policy.py', 'arena_privileged_runner.py',
                    'arena_checkpoint_lab/clock_step.lua']
    frozen = output/'sources'; frozen.mkdir()
    hashes = {}
    for name in source_files:
        data = (ROOT/'tools'/name).read_bytes(); (frozen/name).parent.mkdir(parents=True,exist_ok=True)
        (frozen/name).write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    controller = InternalController()
    initial = observation = observe(client)
    report = dict(schema=1, controller='internal_action_windows_v1', source_hashes=hashes,
                  uses_vision=False, uses_native_search=False, restores=0,
                  coast_baseline=coast,actions=0,
                  input_profile='original_UI_down_release_after_first_native_tick',
                  initial=initial['state'], initial_board=initial['board'], status='running', decisions=0)
    start = time.perf_counter()
    try:
        with (output/'decisions.jsonl').open('w') as stream:
            for index in range(math.ceil(seconds*30)+1):
                proposal = controller.decide(observation)
                reason = proposal.reason
                if not coast and reason in ('unsupported_native_mechanism', 'no_safe_action_window'):
                    report.update(status=reason, final_proposal=asdict(proposal)); break
                if coast:
                    action, frames = 'none', 3
                else:
                    action = proposal.action
                    frames = max(1, min(3, int(proposal.delay*60))) if proposal.delay else 3
                previous = observation
                job = interval(client, frames, action)
                controller.delivered(action, previous['state']['time']) if action != 'none' else None
                observation = observe(client)
                error = forecast_error(previous, observation, action)
                row = dict(index=index, observation=previous, proposal=asdict(proposal),
                           delivered=action, job=job, forecast_error=error)
                stream.write(json.dumps(json_safe(row), ensure_ascii=False, allow_nan=False)+'\n'); stream.flush()
                report['decisions'] += 1
                report['actions'] += int(action!='none')
                report['final'] = observation['state']; report['final_board'] = observation['board']
                report['uninjured_seconds'] = observation['state']['time']-initial['state']['time']
                report['distance_m'] = observation['state']['position']['x']-initial['state']['position']['x']
                report['wall_seconds'] = time.perf_counter()-start
                if index%20 == 0 or action != 'none':
                    print(json.dumps(dict(index=index, time=round(report['uninjured_seconds'],3),
                        x=round(observation['state']['position']['x'],2), health=observation['state']['health'],
                        action=action, reason=reason, compute_ms=round(proposal.evidence['compute_ms'],2))), flush=True)
                if observation['state']['health'] < initial['state']['health'] or job.get('terminated'):
                    report.update(status='first_injury', first_injury_interval=dict(
                        start=previous['state']['time']-initial['state']['time'],
                        end=report['uninjured_seconds']))
                    report['uninjured_seconds'] = report['first_injury_interval']['start']; break
                if observation['board']['stage_index'] > initial['board']['stage_index'] or observation['board']['map_id'] != initial['board']['map_id']:
                    report.update(status='board_passed_no_damage'); break
                if report['uninjured_seconds'] >= seconds:
                    report.update(status='duration_no_damage'); break
                (output/'report.json').write_text(json.dumps(json_safe(report), indent=2, allow_nan=False)+'\n')
            else:
                report['status'] = 'decision_limit'
    except BaseException as error:
        report.update(status='error', error=repr(error)); raise
    finally:
        report['final'] = observation['state']; report['final_board'] = observation['board']
        report['final_observation'] = observation
        if report['status'] != 'first_injury':
            report['uninjured_seconds'] = observation['state']['time']-initial['state']['time']
        report['distance_m'] = observation['state']['position']['x']-initial['state']['position']['x']
        report['wall_seconds'] = time.perf_counter()-start
        report['source_unchanged'] = all(hashlib.sha256((ROOT/'tools'/n).read_bytes()).hexdigest() == h for n,h in hashes.items())
        (output/'report.json').write_text(json.dumps(json_safe(report), indent=2, allow_nan=False)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=73121)
    parser.add_argument('--level', type=int, default=5)
    parser.add_argument('--map', type=int, dest='map_id', default=41)
    parser.add_argument('--board', type=int, default=51012)
    parser.add_argument('--seconds', type=float, default=30.)
    parser.add_argument('--coast', action='store_true', help='No-key baseline and native forecast comparison')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.seconds <= 120 or args.output.exists():
        parser.error('Use a new output directory and a bounded duration <=120 seconds')
    session = InstanceSession('arena'); client = Held(session)
    with session.control():
        try:
            select(client, seed=args.seed, level=args.level, map_id=args.map_id, board=args.board)
            install(client)
            result = evaluate(client, args.output, seconds=args.seconds, coast=args.coast)
            print(json.dumps(json_safe({k:v for k,v in result.items() if k not in ('initial','final','final_proposal','final_observation')}), ensure_ascii=False))
        finally:
            client.execute('MR3A.pause();CS.UnityEngine.Time.captureFramerate=0;MR3A.menu_suppressed=false;MR3A.enable_menu();MR3A.enable_keyboard();return true')


if __name__ == '__main__':
    main()
