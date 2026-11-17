"""Privileged native-engine oracle for fixed-board route research.

This is a bounded depth-first search, not a trained or visual actor. Physics,
traps, damage and candidate evaluation all run in the original client. Undo
only restores VM checkpoints. Committing a window discards earlier history;
failure is reported rather than disguised by restarting/replaying the route.
"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import time

BOARD = """
local f=CS.System.Reflection.BindingFlags.__CastFrom(52)
local l=CS.LevelManager.Instance.GameLevelInfo
local n=CS.NinjaController.Instance.NinjaScript
local g=n._GroundCollider
local i=g and g.BelongToStageIndex or -1
local ss=l:GetType():GetField('_stageList',f):GetValue(l)
local s=i>=0 and i<ss.Count and ss[i]or nil
return {map=l:GetType():GetField('_levelBaseInfo',f):GetValue(l)._levelID,
 stage_index=i,block_index=g and g.BelongToBlockIndex or -1,
 stage_id=s and s:GetType():GetField('_stageBaseInfo',f):GetValue(s)._stageID or -1,
 stage_start=s and s.StageStartX or -1,god=n:IsGodMode(),mounted=n.IsMountState}
"""


class BudgetExceeded(RuntimeError):
    pass


def search_window(gate, *, start, offset, horizon=12, commit=6, max_trials=1200, on_trial=None):
    """Leave the guest at a chosen real checkpoint, or at this window's root.

    A 50ms nominal interval alternates 40/60ms original ticks. offset counts
    committed intervals, so parity survives every window/rebase boundary.
    """
    if not 1 <= commit <= horizon <= 24 or max_trials < 1 or offset < 0:
        raise ValueError('Invalid bounded native search window')
    root = gate.snapshot()['result']['id']
    owned = [root]
    trials = []
    stats = dict(trials=0, rejected_damage=0, restores_ms=[], seconds=0)
    began = time.monotonic()

    def walk(point, depth, path):
        if depth >= horizon:
            return path, False
        ticks = 2 if (offset + depth) % 2 == 0 else 3
        for action in ('none', 'down', 'jump'):
            if stats['trials'] >= max_trials:
                raise BudgetExceeded('Native window trial budget exhausted')
            restored = gate.restore(point)
            stats['restores_ms'].append(restored['ms'])
            job = gate.step(ticks, action)
            stats['trials'] += 1
            safe = not job.get('terminated') and job['after']['health'] == start['health']
            row = dict(depth=depth, action=action, ticks=ticks, safe=safe, job=job)
            trials.append(row)
            if on_trial:
                on_trial(row)
            if not safe:
                stats['rejected_damage'] += 1
                continue
            board = gate.call('exec', code=BOARD)
            if board['mounted'] or board['map'] != start['board']['map']:
                # Different native gameplay contexts require another route.
                continue
            child = gate.snapshot()['result']['id']
            owned.append(child)
            row = dict(action=action, ticks=ticks, job=job, board=board, point=child)
            advanced = path + [row]
            crossed = board['stage_index'] > start['board']['stage_index']
            if crossed:
                return advanced, True
            result = walk(child, depth + 1, advanced)
            if result is not None:
                return result
            gate.restore(point)
            gate.drop(child)
            owned.remove(child)
        return None

    try:
        result = walk(root, 0, [])
        if result is None:
            gate.restore(root)
            return dict(found=False, reason='No safe path within the finite window', root=root,
                        trials=trials, stats=stats)
        path, crossed = result
        count = len(path) if crossed else commit
        selected = path[count - 1]
        gate.restore(selected['point'])
        # Do not replace these observations with field assignments. This is
        # the live state restored by the VM, checked before committing it.
        actual = gate.call('state')
        if actual != selected['job']['after']:
            raise RuntimeError('Chosen VM checkpoint differs from the searched native state')
        return dict(found=True, crossed=crossed, path=deepcopy(path[:count]), root=root,
                    trials=trials, stats=stats)
    except BudgetExceeded as error:
        gate.restore(root)
        return dict(found=False, reason=str(error), root=root, trials=trials, stats=stats)
    except BaseException:
        gate.restore(root)
        raise
    finally:
        stats['seconds'] = time.monotonic() - began


def run(gate, output, *, horizon=12, commit=6, max_trials=1200, max_windows=120):
    """Find one board exit from the current native starting point, if possible.

    Rebase preserves the currently committed guest, releases old RAM history
    and invalidates its earlier checkpoints. There is no restart/replay
    fallback. A stuck finite window leaves its root available for inspection.
    """
    from render import prepare as prepare_renderer, INFO as RENDER_INFO

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    initial = gate.call('state')
    board = gate.call('exec', code=BOARD)
    if (board['stage_index'] < 0 or board['mounted'] or initial.get('content') != 'Running: 1'
            or initial['health'] <= 0 or abs(initial['fixedDeltaTime'] - .02) > 1e-6):
        raise ValueError('Begin route search in a running unmounted battle with original 20ms physics')
    renderer = prepare_renderer(gate)
    start = dict(health=initial['health'], state=initial, board=board)
    report = dict(complete=False, uses_restart_replay=False, game_rollback_complete=False,
                  algorithm='Original-engine bounded DFS; irreversible rolling window commits',
                  horizon=horizon, commit=commit, max_trials=max_trials, start=start,
                  renderer=renderer, windows=[], route=[])
    interval = 0
    started = time.monotonic()
    try:
        report['initial_ram_root'] = gate.rebase()
        with (output / 'trials.jsonl').open('w') as trial_log:
            for index in range(max_windows):
                def save_trial(row):
                    trial_log.write(json.dumps(dict(window=index, **row), ensure_ascii=False) + '\n')
                    trial_log.flush()
                    if not row['safe']:
                        print(f'搜索分支受伤，回溯: 窗{index + 1} 深{row["depth"]} '
                              f'{row["action"]} 帧{row["job"]["after"]["episodeFrame"]}', flush=True)
                window = search_window(gate, start=start, offset=interval, horizon=horizon,
                                       commit=commit, max_trials=max_trials, on_trial=save_trial)
                window.pop('trials')  # Complete per-candidate evidence is streamed above.
                report['windows'].append(window)
                if not window['found']:
                    report['reason'] = window['reason']
                    break
                path = window['path']
                effective = gate.call('exec', code=RENDER_INFO)
                if effective != renderer['requested']:
                    raise RuntimeError('Original scene changed the search renderer size or interval')
                window['renderer'] = effective
                report['route'].extend({key: value for key, value in row.items() if key != 'point'} for row in path)
                interval += len(path)
                state = gate.view['state']
                print(f'原生搜索 {index + 1}: 帧{state["episodeFrame"]} 血{state["health"]} '
                      f'x={state["position"]["x"]:.2f}，试{window["stats"]["trials"]}分支', flush=True)
                if window['crossed']:
                    report['complete'] = True
                    break
                window['rebase'] = gate.rebase()
                (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                report['reason'] = 'Finite window count exhausted'
        report['end'] = dict(state=gate.call('state'), board=gate.call('exec', code=BOARD))
        report['no_health_loss'] = all(
            row['job']['before']['health'] == start['health'] == row['job']['after']['health']
            and not row['job'].get('terminated') for row in report['route'])
        # complete means this native entry -> next grounded board, not the
        # whole arena, random seeds, visual matching or a general solution.
        return report
    except BaseException as error:
        report['error'] = repr(error)
        report['interrupted'] = isinstance(error, KeyboardInterrupt)
        raise
    finally:
        report['seconds'] = time.monotonic() - started
        try:
            report['worker_status'] = gate.vm.request('status')['result']
        except Exception as error:
            report['worker_status_error'] = repr(error)
        for name in ('search.py', 'render.py', 'gate.py', 'game_gate.lua', 'worker.rs'):
            shutil.copy2(Path(__file__).parent / name, output / name)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
