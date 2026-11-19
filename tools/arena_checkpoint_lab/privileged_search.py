"""Search at internal-model action windows, using full VM undo at dead ends.

The model supplies and ranks physical action/time windows. Native execution
checks them. Undo restores both the whole guest and the Python policy state;
there is no restart/replay undo or enumeration of all keys every 50ms.
"""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import time

from arena_fixed_goal import exit_kind
from arena_privileged_policy import InternalController
from arena_privileged_runner import json_safe
from arena_checkpoint_errors import NativeIntervalError
from search import BOARD
from timing_margin import verify


def observe(gate):
    """Read one paused observation without exceeding the native mailbox.

    Dense fixed patterns can contain dozens of enemies. Keep the original
    17-digit gate encoding, read their records in bounded pages, and verify
    that no native state changed while assembling the one observation.
    """
    result=gate.call('exec',code="MR3A.privilegedCached=MR3A.privileged_state();local c=MR3A.privilegedCached;"
        "local h={};for k,v in pairs(c)do if k~='enemies'then h[k]=v end end;return {head=h,count=#c.enemies}")
    observation=result['head'];observation['enemies']=[]
    for offset in range(0,result['count'],2):
        page=gate.call('exec',code=f'local out={{}};local e=MR3A.privilegedCached.enemies;'
            f'for i={offset+1},math.min({offset+2},#e)do out[#out+1]=e[i]end;return out')
        observation['enemies'].extend(page or [])
    gate.call('exec',code='MR3A.privilegedCached=nil;return true')
    if gate.view['state']!=observation['state']:
        raise RuntimeError('Paused native state changed during paged observation')
    return observation


def healthy(observation, health):
    return (observation['state']['health']==health and observation['state']['timeScale']==0
            and not observation['role']['god'] and not observation['role']['mounted'])


def select_alternative(controller, option, stamp):
    controller.scheduled=dict(action=option['action'],due=stamp+option['delay'],
        window=tuple(stamp+d for d in option['window']),origin_stamp=stamp,
        checked_offsets_ms=[-40,40],search_choice=True)


def restore_branch(gate, branch):
    """Do not reuse pending absolute times or input cooldowns from a future."""
    result=gate.restore(branch['point'])
    if gate.call('state')!=branch['observation']['state']:
        raise RuntimeError('VM branch restore differs from its original native state')
    return deepcopy(branch['controller']),deepcopy(branch['observation']),result['ms']


def run(gate, output, *, max_decisions=4000,max_backtracks=80,wall_seconds=1800,
        progress=None,certify=True):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    progress=progress or (lambda value:None)
    controller=InternalController(collect_alternatives=True)
    observation=observe(gate)
    if not healthy(observation,5000):
        raise ValueError('Expert search requires a healthy unmounted original entry')
    board=gate.call('exec',code=BOARD)
    initial=gate.snapshot()['result']['id'];initial_observation=deepcopy(observation)
    owned={initial};branches=[];route=[];restores=[];started=time.monotonic()
    report=dict(schema=1,algorithm='native_internal_action_windows_with_VM_dead_end_backtracking_v1',
        start=dict(state=observation['state'],health=5000,board=board),
        uses_restart_replay=False,uses_vision=False,native_decision=True,
        status='running',nominal_complete=False,timing_robust=False,complete=False,
        decisions=0,backtracks=0,route=route)

    def save():
        report.update(route=route,wall_seconds=time.monotonic()-started,
            restores_ms=restores,retained_branch_points=len(branches),
            end=dict(state=observation['state'],board=board),
            game_seconds=observation['state']['time']-initial_observation['state']['time'],
            distance_m=observation['state']['position']['x']-initial_observation['state']['position']['x'])
        temporary=output/'report.tmp'
        temporary.write_text(json.dumps(json_safe(report),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        temporary.replace(output/'report.json')

    def backtrack(reason):
        nonlocal controller,observation,board,route
        report['last_dead_end']=reason
        if report['backtracks']>=max_backtracks:
            report['status']='backtrack_budget';return False
        while branches:
            branch=branches[-1]
            if branch['next']>=len(branch['options']):
                gate.drop(branch['point']);owned.discard(branch['point']);branches.pop();continue
            controller,observation,elapsed=restore_branch(gate,branch)
            restores.append(elapsed);report['backtracks']+=1
            route=route[:branch['route_length']]
            option=branch['options'][branch['next']];branch['next']+=1
            select_alternative(controller,option,observation['state']['time'])
            board=gate.call('exec',code=BOARD)
            progress(dict(phase='model_window_backtrack',backtracks=report['backtracks'],
                world_x=observation['state']['position']['x'],restore_ms=elapsed,option=option))
            return True
        report['status']='model_windows_exhausted';return False

    try:
        with (output/'decisions.jsonl').open('w') as stream:
            for index in range(max_decisions):
                if time.monotonic()-started>=wall_seconds:
                    report['status']='wall_budget';break
                previous_controller=deepcopy(controller)
                proposal=controller.decide(observation);report['decisions']+=1
                if proposal.reason=='unsupported_native_mechanism':
                    report.update(status='unsupported_native_mechanism',missing=asdict(proposal));break
                if proposal.reason in ('no_safe_action_window','selected_internal_window_invalidated'):
                    if backtrack(dict(reason=proposal.reason,proposal=asdict(proposal))):
                        save();continue
                    break
                options=proposal.evidence.get('alternatives',[])
                # Record only an actual choice between model-approved physical
                # windows. Coasting and the remaining approach are not branches.
                if options and previous_controller.scheduled is None and controller.scheduled is not None:
                    if len(options)>1:
                        point=gate.snapshot()['result']['id'];owned.add(point)
                        branches.append(dict(point=point,controller=previous_controller,
                            observation=deepcopy(observation),route_length=len(route),options=options,next=1))
                    controller.scheduled['search_choice']=True
                action=proposal.action
                frames=max(1,min(3,int(proposal.delay*60))) if proposal.delay else 3
                before=observation
                try:
                    job=gate.render_step(frames,action)
                except NativeIntervalError as error:
                    if backtrack(dict(reason='native_interval_invalid',job=error.job)):
                        save();continue
                    break
                if action!='none':
                    controller.delivered(action,before['state']['time'])
                observation=observe(gate)
                board=gate.call('exec',code=BOARD)
                record=dict(index=index,observation=before,proposal=asdict(proposal),action=action,job=job,board=board)
                stream.write(json.dumps(json_safe(record),ensure_ascii=False,allow_nan=False)+'\n');stream.flush()
                samples=job.get('samples') or []
                if (not healthy(observation,5000) or job.get('terminated')
                        or any(s['health']!=5000 for s in samples)):
                    if backtrack(dict(reason='native_damage_or_protection',job=job)):
                        save();continue
                    break
                route.append(dict(action=action,ticks=job['after']['episodeFrame']-job['before']['episodeFrame'],
                    frames=frames,job=job,board=board))
                if index%20==0 or action!='none':
                    progress(dict(phase='expert_forward',decisions=report['decisions'],
                        game_seconds=observation['state']['time']-initial_observation['state']['time'],
                        world_x=observation['state']['position']['x'],health=observation['state']['health'],
                        action=action,backtracks=report['backtracks'],compute_ms=proposal.evidence['compute_ms']))
                    save()
                crossed=exit_kind(report['start']['board'],board)
                if crossed:
                    report.update(status='nominal_native_exit',nominal_complete=True,exit_kind=crossed)
                    if certify:
                        report['status']='checking_native_endpoints';save()
                        report['timing_validation']=verify(gate,route,initial_point=initial,
                            initial_state=report['start']['state'],start=report['start'],board_code=BOARD,
                            whole_board=True,on_result=lambda check:progress(dict(phase='native_endpoint_check',**check)))
                        report['timing_robust']=bool(report['timing_validation']['passed'])
                        report['status']='native_endpoints_passed' if report['timing_robust'] else 'native_endpoints_failed'
                    # Fresh entry and deployed visual acceptance are separate;
                    # this search must not silently publish nominal routes.
                    report['complete']=False
                    break
            else:
                report['status']='decision_budget'
    except BaseException as error:
        report.update(status='error',error=repr(error));raise
    finally:
        save()
        gate.restore(initial)
        for point in owned:
            if point in gate.points:
                gate.drop(point)
    return report
