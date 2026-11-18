"""Native-state-guided search, with independent timing tests before commit."""
from math import isfinite
from timing_margin import verify


def rejected_prefix(forecast,history_length,audit):
    failure=audit.get('failure',{})
    # Later keys are triggered by nominal world X. Changing a key whose
    # target is beyond every position reached before damage cannot prevent
    # that damage. Include every earlier row (also non-monotone X paths),
    # and the perturbed key itself; leave later alternatives available.
    end=len(forecast)-1
    if (failure.get('reason')=='native_damage'and 'max_world_x'in failure
            and isfinite(failure['max_world_x'])):
        reachable=[i for i,row in enumerate(forecast)
                   if row['job']['before']['position']['x']<=failure['max_world_x']+1e-5]
        event=failure['event']['row_index']-history_length
        end=max(event,max(reachable,default=-1))
    return tuple(row['action']for row in forecast[:end+1])


def window(gate,*,searcher,history,initial_point,initial_state,board_code,**kwargs):
    forbidden=set(kwargs.pop('forbidden_prefixes',()))
    budget=kwargs.pop('max_trials',1200)
    root=kwargs.pop('root_point',None)
    audits=[];used=0
    previous=next((r['job']['before']['episodeFrame']for r in reversed(history)if r['action']!='none'),None)
    while used<budget:
        result=searcher(gate,**kwargs,max_trials=budget-used,root_point=root,
                        forbidden_prefixes=forbidden,guided=True,retain_forecast=True,last_input_frame=previous)
        root=result['root'];used+=result['stats']['trials']
        if not result['found']:
            result['timing_attempts']=audits
            return result
        path=result['path'];forecast=result.pop('forecast_path')
        combined=history+forecast
        selected={len(history)+i for i,row in enumerate(path)if row['action']!='none'}
        end_frame=forecast[-1]['job']['after']['episodeFrame']
        upcoming=next((i for i,row in enumerate(forecast)if i>=len(path)and row['action']!='none'
                       and row['job']['before']['episodeFrame']+2<end_frame),None)
        if upcoming is not None:selected.add(len(history)+upcoming)
        def progress(check):
            print(f'独立80ms窗口: 操作{check["event"]} 偏移{check["shift_ms"]}ms 通过={check["passed"]}',flush=True)
        audit=(verify(gate,combined,initial_point=initial_point,initial_state=initial_state,
                      start=kwargs['start'],board_code=board_code,selected_rows=selected,on_result=progress)
               if selected else dict(passed=True,operations=0,window_ms=80,checks=[]))
        audits.append(audit)
        if audit['passed']:
            committed={r['point']for r in path}
            for point in {r['point']for r in forecast}-committed:gate.drop(point)
            result['timing_attempts']=audits
            result['stats']['total_candidate_trials']=used
            return result
        prefix=rejected_prefix(forecast,len(history),audit)
        audit['rejected_forecast_prefix']=list(prefix)
        forbidden.add(prefix)
        gate.restore(root)
        for point in {r['point']for r in forecast}:gate.drop(point)
    return dict(found=False,root=root,trials=[],path=[],timing_attempts=audits,
                reason='Native proposal budget exhausted while repairing operation timing windows',
                stats=dict(trials=used,restores_ms=[]))
