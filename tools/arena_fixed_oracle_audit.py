#!/usr/bin/env python3
"""Verify a stored route on arena without any visual decisions or search undo."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from arena_local import LocalClient,ROOT
from arena_bootstrap import wait_job
from arena_visual_runner import prepare
from runtime import InstanceSession


def plan(route):
    if not route.get('complete')or route.get('uses_restart_replay')is not False:
        raise ValueError('A diagnostic requires a complete native route')
    initial=route['start']['state']
    previous=initial
    events=[]
    for row in route['steps']:
        if (row['before']!=previous or row['after']['health']!=initial['health']
                or row['before']['health']!=initial['health']
                or row['after']['episodeFrame']-row['before']['episodeFrame']!=row['ticks']
                or row['relative_tick']!=row['before']['episodeFrame']-initial['episodeFrame']):
            raise ValueError('The stored route has a damaged or discontinuous interval')
        if row['action']not in ('none','jump','down'):raise ValueError('Unsupported original input')
        if row['action']!='none':
            events.append(dict(relative_tick=row['relative_tick'],action=row['action']))
        previous=row['after']
    return dict(events=events,duration_ticks=previous['episodeFrame']-initial['episodeFrame'])


def entry_comparison(route,state,board):
    expected=route['start'];s=expected['state'];old=expected['board']
    return dict(health_equal=state['health']==s['health'],physics_equal=state['physics']==s['physics'],
        episode_frame_delta=state['episodeFrame']-s['episodeFrame'],
        local_x_error=(state['position']['x']-board['stage_start'])-(s['position']['x']-old['stage_start']),
        y_error=state['position']['y']-s['position']['y'],
        context_equal=all(board[k]==old[k]for k in ('map','stage_index','stage_id')),
        scope='Finite entry fields only; no claim of identical full initial state')


def delay_events(specification,delays):
    events=[]
    if any(type(i)is not int or not 0<=i<len(specification['events'])for i in delays):
        raise ValueError('Perturb only a recorded operation index')
    for index,event in enumerate(specification['events']):
        delay=delays.get(index,0)
        if type(delay)is not int or not -5<=delay<=5:raise ValueError('Input perturbation is limited to five native ticks')
        changed=dict(event,relative_tick=event['relative_tick']+delay,source_tick=event['relative_tick'])
        if changed['relative_tick']<0 or events and changed['relative_tick']<=events[-1]['relative_tick']:
            raise ValueError('A perturbation cannot change operation order')
        events.append(changed)
    return dict(specification,events=events)


def interval_execution(client,route,output):
    rows=[]
    first_divergence=None
    for index,row in enumerate(route['steps']):
        client.execute(f'return MR3A.advance({row["ticks"]},{json.dumps(row["action"])})')
        job=wait_job(client,'MR3A.job',timeout=20)
        before,after=job['before'],job['after']
        expected=row['after']
        delta=dict(x=after['position']['x']-expected['position']['x'],
                   y=after['position']['y']-expected['position']['y'],
                   tick=after['episodeFrame']-before['episodeFrame']-row['ticks'],
                   physics_equal=after['physics']==expected['physics'])
        if first_divergence is None and (abs(delta['x'])>.2 or abs(delta['y'])>.2
                or delta['tick']!=0 or not delta['physics_equal']):
            first_divergence=dict(index=index,expected=expected,actual=after,delta=delta)
        rows.append(dict(index=index,action=row['action'],job=job,delta=delta))
        if index%20==0:
            print('Oracle intervals',index,'HP',after['health'],flush=True)
            (output/'intervals.json').write_text(json.dumps(rows,indent=2))
        if after['health']<=0:break
    (output/'intervals.json').write_text(json.dumps(rows,indent=2))
    return dict(mode='source_intervals',first_divergence=first_divergence,
                intervals_executed=len(rows),evaluation=client.execute('return MR3A.vision_evaluation()'))


def audit(queue,key,output,mode,capture_fps,seed=None,delays=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    coverage=json.loads((queue/'coverage.json').read_text())
    case=next(c for c in json.loads((queue/'inventory.json').read_text())['contexts']if c['key']==key)
    path=Path(coverage['cases'][key]['route']);raw=path.read_bytes();route=json.loads(raw)
    specification=plan(route)
    delays=delays or {}
    if delays and mode=='source_intervals':raise ValueError('Perturbations require a continuous diagnostic')
    specification=delay_events(specification,delays)
    seed=route['start']['state']['seed']if seed is None else seed
    from arena_checkpoint_lab.search import BOARD
    session=InstanceSession('arena')
    class Held(LocalClient):
        def execute(self,*args,**kwargs):return super().execute(*args,**dict(kwargs,lease_held=True))
    client=Held(session)
    helper=ROOT/'tools/arena_checkpoint_lab/oracle_route.lua'
    dependencies=[Path(__file__),helper,ROOT/'arena/Local/environment.lua',ROOT/'arena/Local/native_selection.lua',
                  ROOT/'arena/Local/vision_eval.lua']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()for p in dependencies}
    capture_fps=60 if mode=='source_intervals'else capture_fps
    result=dict(schema=1,key=key,mode=mode,capture_fps=capture_fps,seed=seed,input_delays=delays,
        route=str(path),route_sha256=hashlib.sha256(raw).hexdigest(),source_hashes=hashes,
        scope='Independent route execution diagnostic, not snapshot undo or a visual-policy success',
        search_undo_uses_replay=False)
    with session.control():
        state=client.execute('return MR3A.state()')
        if state['timeScale']!=0:raise RuntimeError('Pause the named arena before the audit')
        try:
            prepare(client,seed,case['level'],case['map'],case['selection']['pins'],start=case['slot'],timeout=150)
            state=client.execute('return MR3A.state()');board=client.execute(BOARD)
            result['entry']=dict(state=state,board=board,comparison=entry_comparison(route,state,board))
            (output/'setup.json').write_text(json.dumps(result,indent=2))
            if not result['entry']['comparison']['context_equal']or state['health']!=5000 or board['god']or board['mounted']:
                raise RuntimeError('Original initialization did not provide the requested unprotected board')
            if mode=='source_intervals':
                result['execution']=interval_execution(client,route,output)
            else:
                client.execute(helper.read_text())
                spec=dict(specification,mode=mode,capture_fps=capture_fps)
                client.execute('return MR3A.run_fixed_oracle(json.parse('+json.dumps(json.dumps(spec))+'))')
                result['execution']=wait_job(client,'MR3A.fixedOracleAudit',timeout=140)
            final=result['execution']['evaluation'];result['final']=final
            result['input_schedule_exact']=(len(result['execution']['actions'])==len(specification['events'])
                and all(a['actual_tick']==a['target_tick']for a in result['execution']['actions']))if mode!='source_intervals'else(
                    result['execution']['intervals_executed']==len(route['steps']))
            result['no_damage']=bool(final['health']==5000 and final['minHealth']==5000 and final['damage']==0)
            result['exit']=bool(final['map']!=case['map']or final['stageIndex']>=case['slot'])
            result['passed']=result['no_damage']and result['exit']
        except BaseException as error:
            result['error']=repr(error)
            try:result['unfinished_execution']=client.execute('return MR3A.fixedOracleAudit')
            except Exception:pass
            raise
        finally:
            try:
                client.execute('if MR3A.fixedOracleAudit then MR3A.fixedOracleAudit.cancel=true end;return true')
                deadline=time.monotonic()+10
                while client.execute('return MR3A.busy')and time.monotonic()<deadline:time.sleep(.1)
                if client.execute('return MR3A.busy'):raise RuntimeError('The original job is still active')
                result['cleanup']=client.execute('MR3A.pause();CS.UnityEngine.Time.captureFramerate=0;'
                    'MR3A.visionEvalEnabled=false;MR3A.menu_suppressed=false;MR3A.enable_menu();MR3A.enable_keyboard();return MR3A.state()')
            except Exception as error:result['cleanup_error']=repr(error)
            result['sources_unchanged']=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
            (output/'report.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:result.get(k)for k in ('key','mode','capture_fps','passed','no_damage','exit','error','cleanup_error')}),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--queue',type=Path,default=ROOT/'debug/arena-client/fixed-route-work/batch-all')
    p.add_argument('--case',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=('source_intervals','continuous_ticks'),required=True)
    p.add_argument('--capture-fps',type=int,choices=(0,60),default=0)
    p.add_argument('--seed',type=int)
    p.add_argument('--delay-event',action='append',default=[],help='Diagnostic only: operation index:delay in original ticks')
    a=p.parse_args();delays={int(i):int(t)for i,t in(x.split(':',1)for x in a.delay_event)}
    audit(a.queue,a.case,a.output,a.mode,a.capture_fps,a.seed,delays)
