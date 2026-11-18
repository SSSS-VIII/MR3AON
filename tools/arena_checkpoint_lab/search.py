"""Privileged native-engine oracle for fixed-board route research.

This is a bounded depth-first search, not a trained or visual actor. Physics,
traps, damage and candidate evaluation all run in the original client. Undo
only restores VM checkpoints. The opt-in file-backed worker retains older
windows for genuine backtracking; the original rolling mode still rebases.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import time
from arena_fixed_goal import exit_kind
from arena_checkpoint_errors import NativeIntervalError

LOADED_SOURCE = Path(__file__).read_bytes()

BOARD = """
local f=CS.System.Reflection.BindingFlags.__CastFrom(52)
local l=CS.LevelManager.Instance.GameLevelInfo
local n=CS.NinjaController.Instance.NinjaScript
local g=n._GroundCollider
local i=g and g.BelongToStageIndex or -1
local ss=l:GetType():GetField('_stageList',f):GetValue(l)
local s=i>=0 and i<ss.Count and ss[i]or nil
if i>=ss.Count then s=l:GetType():GetField('_currLoopStage',f):GetValue(l)end
return {map=l:GetType():GetField('_levelBaseInfo',f):GetValue(l)._levelID,
 stage_index=i,stage_count=ss.Count,loop=i>=ss.Count,instance=s and s:GetHashCode()or nil,
 block_index=g and g.BelongToBlockIndex or -1,
 stage_id=s and s:GetType():GetField('_stageBaseInfo',f):GetValue(s)._stageID or -1,
 stage_start=s and s.StageStartX or -1,god=n:IsGodMode(),mounted=n.IsMountState}
"""

RESTING=frozenset(('runonline','runonlinedown','runonground','slideonground'))


class BudgetExceeded(RuntimeError):
    pass


def search_window(gate, *, start, offset, horizon=12, commit=6, max_trials=1200, on_trial=None, cache_prefix=0,
                  root_point=None, forbidden_prefixes=(),early_jump=False,guided=False,retain_forecast=False,
                  last_input_frame=None):
    """Leave the guest at a chosen real checkpoint, or at this window's root.

    A 50ms nominal interval alternates 40/60ms original ticks. offset counts
    committed intervals, so parity survives every window/rebase boundary.
    """
    if not 1 <= commit <= horizon <= 24 or max_trials < 1 or offset < 0 or not 0<=cache_prefix<=4:
        raise ValueError('Invalid bounded native search window')
    root = gate.snapshot()['result']['id'] if root_point is None else root_point
    owned = [root]
    trials = []
    stats = dict(trials=0, rejected_damage=0, restores_ms=[], action_limits_tried=[], seconds=0)
    stats['prefix_cache_hits']=0
    stats['rejected_invalid_interval']=0
    stats['early_jump_hint']=False
    stats['blocked_rope_hint']=False
    force_first_jump=False
    prefix={}
    unsafe_actions = set()
    decisions={}
    stats['native_decisions']=[]
    stats['timing_spacing_pruned']=0
    stats['proposal_deviation_limits_tried']=[]
    began = time.monotonic()

    def release(keep):
        for identity in owned:
            if identity not in keep:gate.drop(identity)

    def walk(point, depth, path, remaining_cost):
        if depth>=commit and tuple(r['action']for r in path[:commit])in forbidden_prefixes:
            return None
        if depth >= horizon:
            return path, False
        ticks = 2 if (offset + depth) % 2 == 0 else 3
        order=('none','down','jump')
        if guided:
            from native_policy import read,decision,refine
            if point not in decisions:
                observation=read(gate)
                decisions[point]=refine(gate,point,observation,decision(observation))
                stats['native_decisions'].append(dict(point=point,**decisions[point]))
            order=tuple(decisions[point]['order'])
            previous=next((r['job']['before']['episodeFrame']for r in reversed(path)if r['action']!='none'),last_input_frame)
            current=path[-1]['job']['after']['episodeFrame']if path else gate.view['state']['episodeFrame']
            if previous is not None and current-previous<=2:
                stats['timing_spacing_pruned']+=sum(action!='none'for action in order)
                order=tuple(action for action in order if action=='none')
        for action in (('jump',)if force_first_jump and depth==0 else order):
            # In guided mode a key is free when the native policy requests it.
            # Limit disagreements with that policy, rather than key count.
            cost = int(action != order[0]) if guided else int(action != 'none')
            if cost > remaining_cost or (point, action) in unsafe_actions:
                continue
            cached=prefix.get(point)if action=='none'else None
            if cached is None and stats['trials'] >= max_trials:
                raise BudgetExceeded('Native window trial budget exhausted')
            if cached is not None:
                stats['prefix_cache_hits']+=1
                child=cached['point']
                row=cached
                stats['restores_ms'].append(gate.restore(child)['ms'])
                advanced=path+[row]
                crossed=exit_kind(start['board'],row['board'])is not None
                result=(advanced,True)if crossed else walk(child,depth+1,advanced,remaining_cost-cost)
                if result is not None:
                    return result
                gate.restore(point)
                continue
            restored = gate.restore(point)
            stats['restores_ms'].append(restored['ms'])
            interval_error=None
            try:
                job = gate.step(ticks, action)
            except NativeIntervalError as error:
                # Reject this candidate without weakening the exact step
                # contract or publishing a 4-tick run as a requested 3 ticks.
                job=error.job
                interval_error=str(error)
                stats['rejected_invalid_interval']+=1
            stats['trials'] += 1
            safe = interval_error is None and not job.get('terminated') and job['after']['health'] == start['health']
            row = dict(depth=depth, action=action, ticks=ticks, safe=safe, job=job)
            if interval_error is not None:row['interval_error']=interval_error
            trials.append(row)
            if on_trial:
                on_trial(row)
            if not safe:
                if job.get('terminated')or job['after']['health']!=start['health']:stats['rejected_damage'] += 1
                unsafe_actions.add((point, action))
                continue
            board = gate.call('exec', code=BOARD)
            goal = exit_kind(start['board'], board)
            if board['mounted'] or (board['map'] != start['board']['map'] and goal is None):
                # Different native gameplay contexts require another route.
                continue
            child = gate.snapshot()['result']['id']
            owned.append(child)
            row = dict(action=action, ticks=ticks, job=job, board=board, point=child)
            keep=(action=='none'and depth<cache_prefix and all(r['action']=='none'for r in path))
            if keep:
                prefix[point]=row
            advanced = path + [row]
            crossed = goal is not None
            if crossed:
                return advanced, True
            result = walk(child, depth + 1, advanced, remaining_cost - cost)
            if result is not None:
                return result
            gate.restore(point)
            if not keep:
                gate.drop(child)
                owned.remove(child)
        return None

    try:
        result = None
        # Guided search first follows the native policy, then permits one,
        # two, ... disagreements. An early alternative gets a turn before
        # combinatorial late corrections consume the window's budget.
        # Legacy mode retains its minimum-input search.
        for limit in range(horizon + 1):
            stats['proposal_deviation_limits_tried'if guided else'action_limits_tried'].append(limit)
            result = walk(root, 0, [], limit)
            if early_jump and limit==0 and result is None and trials:
                before=trials[0]['job']['before'];after=trials[-1]['job']['after']
                widths=[2*c['extents']['x']for c in before.get('colliders',[])
                    if c.get('name')=='Role'and c.get('enabled')and c.get('extents',{}).get('x',0)>0]
                x0=before.get('position',{}).get('x');x1=after.get('position',{}).get('x')
                if (widths and x0 is not None and x1 is not None and abs(x1-x0)<2*max(widths)
                        and before['physics'].split(':')[0].lower()=='runonlinedown'):
                    # The original no-input branch is blocked under a rope.
                    # Prioritize its native up-flip and at most one following
                    # key, still evaluated by the original engine and budget.
                    stats['blocked_rope_hint']=True;force_first_jump=True
                    try:result=walk(root,0,[],2)
                    finally:force_first_jump=False
            if result is not None:
                break
        if early_jump and result is not None and offset>0:
            path,crossed=result
            before=path[0]['job']['before'];after=path[-1]['job']['after']
            heights=[2*c['extents']['y']for c in before.get('colliders',[])
                     if c.get('name')=='Role'and c.get('enabled')and c.get('extents',{}).get('y',0)>0]
            y0=before.get('position',{}).get('y');y1=after.get('position',{}).get('y')
            if (not crossed and heights
                    and before['physics'].split(':')[0].lower()in ('fallfromrun','fall')
                    and y0 is not None and y1 is not None and y0-y1>2*max(heights)):
                # A no-input or late-input rollout can survive this horizon while
                # already falling far below the ledge. Try one early native
                # jump before accepting it; no analytical physics or damage
                # override determines the candidate's safety.
                stats['early_jump_hint']=True
                force_first_jump=True
                try:
                    candidate=walk(root,0,[],1)
                    if candidate is not None:
                        proposed,exited=candidate
                        if exited or proposed[-1]['job']['after']['position']['y']>y1+max(heights)/2:
                            result=candidate
                except BudgetExceeded:
                    pass  # The already verified original rollout remains valid.
                finally:force_first_jump=False
        if result is None:
            gate.restore(root)
            release({root})
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
        keep={root,*(r['point']for r in (path if retain_forecast else path[:count]))}
        release(keep)
        result=dict(found=True, crossed=crossed, path=deepcopy(path[:count]), root=root,
                    trials=trials, stats=stats)
        if retain_forecast:result['forecast_path']=deepcopy(path)
        return result
    except BudgetExceeded as error:
        gate.restore(root)
        release({root})
        return dict(found=False, reason=str(error), root=root, trials=trials, stats=stats)
    except BaseException:
        gate.restore(root)
        release({root})
        raise
    finally:
        stats['seconds'] = time.monotonic() - began


def run(gate, output, *, horizon=12, commit=6, max_trials=1200, max_windows=120, collector=None,
        retain_history=False,native_decision=False):
    """Find one board exit from the current native starting point, if possible.

    Rolling mode rebases after each window. Retained mode keeps real earlier
    roots and rejects a previous committed prefix when its continuation fails.
    Both modes keep finite budgets and never restart/replay to undo a branch.
    """
    from render import prepare as prepare_renderer, INFO as RENDER_INFO

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    if native_decision and not retain_history:raise ValueError('Timing repair needs retained original checkpoints')
    names=('search.py','render.py','gate.py','game_gate.lua')+(
        ('worker_file.rs','ram_file.rs','ram_file.patch','ram_restore.patch','restore_trace.patch')if retain_history else('worker.rs',))
    if native_decision:names+=('native_policy.py','native_observation.lua','timing_margin.py','guided_search.py')
    sources = {name: (LOADED_SOURCE if name == 'search.py' else (Path(__file__).parent / name).read_bytes())
               for name in names}
    if collector is not None:
        sources['collector.py'] = (Path(__file__).parent / 'collector.py').read_bytes()
    for name, data in sources.items():
        (output / name).write_bytes(data)
    initial = gate.call('state')
    if retain_history and not gate.vm.request('status')['result'].get('file_ram'):
        raise RuntimeError('Cross-window history requires the validated file-backed worker')
    board = gate.call('exec', code=BOARD)
    if (board['stage_index'] < 0 or board['mounted'] or initial.get('content') != 'Running: 1'
            or initial['health'] <= 0 or abs(initial['fixedDeltaTime'] - .02) > 1e-6):
        raise ValueError('Begin route search in a running unmounted battle with original 20ms physics')
    renderer = prepare_renderer(gate)
    if native_decision:
        from collector import install_lua
        install_lua(gate,(Path(__file__).parent/'native_observation.lua').read_text())
    start = dict(health=initial['health'], state=initial, board=board)
    report = dict(complete=False, uses_restart_replay=False, game_rollback_complete=False,
                  algorithm='Original-engine iterative input-count DFS; irreversible rolling window commits',
                  horizon=horizon, commit=commit, max_trials=max_trials, start=start,
                  renderer=renderer, windows=[], route=[])
    report['retains_window_roots']=retain_history
    report['native_decision']=native_decision
    if retain_history:report['backtrack_policy']='nearest_original_resting_root; finite search heuristic'
    process=getattr(gate.vm,'process',None)if hasattr(gate,'vm')else None
    if process is not None:
        with Path(f'/proc/{process.pid}/exe').open('rb')as stream:
            report['worker_binary_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
        report['worker_capabilities']=gate.vm.request('status')['result']
        report['source_scope']='Editor source snapshot; the executable SHA identifies the actual running backend'
    if retain_history:report['algorithm']='Original-engine input-count DFS with whole-VM cross-window backtracking'
    if native_decision:report['algorithm']='Native-policy limited-discrepancy search with exact-engine lookahead and independent 80ms operation windows'
    report['backtracks']=[]
    history=[]
    nominal=[]
    forbidden={}
    retry_root=None
    retry_horizon=None
    interval = 0
    started = time.monotonic()
    def backtrack(window,index,reason,target_row=None):
        nonlocal interval,retry_root,retry_horizon
        if not retain_history or not history:return False
        abandoned_windows=[history.pop()]
        while history and target_row is not None and abandoned_windows[-1]['route_length']>target_row:
            abandoned_windows.append(history.pop())
        while history and not abandoned_windows[-1]['resting']:
            abandoned_windows.append(history.pop())
        previous=abandoned_windows[-1]
        restored=gate.restore(previous['root'])
        abandoned={window['root']}
        for old in abandoned_windows:abandoned.update([old['root'],*old['points']])
        abandoned.discard(previous['root']);abandoned.discard(report['initial_ram_root']['result']['id'])
        for identity in abandoned:gate.drop(identity)
        if collector is not None:collector.rewind(previous['reference_count'])
        report['backtracks'].append(dict(from_attempt=index,to_attempt=previous['attempt'],
            root=previous['root'],restore_ms=restored['ms'],reason=reason,
            skipped_attempts=[old['attempt']for old in abandoned_windows],target_row=target_row))
        for old in abandoned_windows:report['windows'][old['attempt']]['backtracked']=True
        del report['route'][previous['route_length']:];del nominal[previous['route_length']:]
        interval=previous['offset'];retry_root=previous['root']
        retry_horizon=min(24,max(window['horizon'],previous['horizon'])+commit*len(abandoned_windows))
        print(f'跨窗回退: 窗{index+1} → 窗{previous["attempt"]+1}，恢复{restored["ms"]:.2f}ms，{reason}',flush=True)
        return True
    try:
        report['initial_ram_root'] = gate.rebase()
        if retain_history and not report['initial_ram_root']['result'].get('file_backed'):
            raise RuntimeError('The new RAM root was not backed successfully; no history search started')
        if collector is not None:
            collector.begin(gate, report['initial_ram_root']['result']['id'], start)
        with (output / 'trials.jsonl').open('w') as trial_log:
            for index in range(max_windows):
                damage_count = 0
                def save_trial(row):
                    nonlocal damage_count
                    trial_log.write(json.dumps(dict(window=index, **row), ensure_ascii=False) + '\n')
                    trial_log.flush()
                    if not row['safe'] and (row['job'].get('terminated')or row['job']['after']['health']!=start['health']):
                        damage_count += 1
                        if damage_count == 1 or damage_count % 25 == 0:
                            print(f'搜索回溯: 窗{index + 1} 已拒{damage_count}个扣血分支，'
                                  f'帧{row["job"]["after"]["episodeFrame"]}', flush=True)
                effective_horizon=retry_horizon or horizon
                arguments=dict(start=start,offset=interval,horizon=effective_horizon,commit=commit,
                    max_trials=max_trials,on_trial=save_trial,root_point=retry_root,
                    forbidden_prefixes=forbidden.get(retry_root,()),cache_prefix=4 if retain_history else 0,
                    early_jump=retain_history and not native_decision)
                if native_decision:
                    from guided_search import window as guided_window
                    window=guided_window(gate,searcher=search_window,history=nominal,
                        initial_point=report['initial_ram_root']['result']['id'],initial_state=start['state'],
                        board_code=BOARD,**arguments)
                else:window=search_window(gate,**arguments)
                window['horizon']=effective_horizon
                window.pop('trials')  # Complete per-candidate evidence is streamed above.
                report['windows'].append(window)
                if not window['found']:
                    if backtrack(window,index,window['reason']):
                        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
                        continue
                    report['reason'] = window['reason']
                    break
                path = window['path']
                if retain_history:
                    forbidden.setdefault(window['root'],set()).add(tuple(r['action']for r in path))
                    history.append(dict(root=window['root'],route_length=len(report['route']),
                                        offset=interval,attempt=index,points=[r['point']for r in path],
                                        horizon=effective_horizon,
                                        resting=path[0]['job']['before']['physics'].split(':')[0].lower()in RESTING,
                                        reference_count=len(collector.rows)if collector is not None else 0))
                    retry_root=None
                    retry_horizon=None
                effective = gate.call('exec', code=RENDER_INFO)
                if effective != renderer['requested'] and not window['crossed']:
                    raise RuntimeError('Original scene changed the search renderer size or interval')
                window['renderer'] = effective
                report['route'].extend({key: value for key, value in row.items() if key != 'point'} for row in path)
                nominal.extend(path)
                if collector is not None:
                    collector.window(gate, path, index)
                    if gate.call('state') != path[-1]['job']['after']:
                        raise RuntimeError('Reference capture did not restore the committed native state')
                    report['references'] = collector.status()
                interval += len(path)
                state = gate.view['state']
                print(f'原生搜索 {index + 1}: 帧{state["episodeFrame"]} 血{state["health"]} '
                      f'x={state["position"]["x"]:.2f}，试{window["stats"]["trials"]}分支', flush=True)
                if window['crossed']:
                    if native_decision:
                        from timing_margin import verify
                        with (output/'timing-validation.jsonl').open('a')as audit_log:
                            def timing_progress(check):
                                audit_log.write(json.dumps(dict(attempt=index,**check),ensure_ascii=False)+'\n')
                                audit_log.flush()
                                print(f'整板80ms验证: 操作{check["event"]} 偏移{check["shift_ms"]}ms '
                                      f'通过={check["passed"]}',flush=True)
                            validation=verify(gate,nominal,initial_point=report['initial_ram_root']['result']['id'],
                                initial_state=start['state'],start=start,board_code=BOARD,whole_board=True,
                                on_result=timing_progress)
                        report['timing_validation']=validation
                        if not validation['passed']:
                            failure=validation['failure']
                            report.setdefault('timing_rejections',[]).append(validation)
                            target=failure['event']['row_index']
                            print(f'整板80ms独立容差失败，回退修正操作所在窗: row={target}',flush=True)
                            if backtrack(window,index,'independent_operation_margin_failed',target):continue
                            report['reason']='No retained prefix can repair the operation timing margin'
                            break
                    report['complete'] = True
                    report['exit_kind'] = exit_kind(start['board'], path[-1]['board'])
                    break
                if not retain_history:window['rebase'] = gate.rebase()
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
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
