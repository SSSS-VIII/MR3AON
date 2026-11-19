"""Native-state-guided search, with independent timing tests before commit."""
from math import isfinite
from timing_margin import verify
from prefix_cache import PrefixCache


def rejected_prefix(forecast,history_length,audit):
    failure=audit.get('failure',{})
    # Later keys are triggered by nominal world X. Changing a key whose
    # target is beyond every position reached before damage cannot prevent
    # that damage. Include every earlier row (also non-monotone X paths),
    # and the perturbed key itself; leave later alternatives available.
    end=len(forecast)-1
    if failure.get('reason')in('nominal_operation_has_no_effect',
                              'operation_prerequisite_mismatch','operation_effect_mismatch',
                              'input_transport_repeat_too_close'):
        # A later suffix cannot change an already failed operation check.
        # These prefixes are local to this exact VM root and input history.
        row=(failure.get('event')or{}).get('row_index')
        if type(row)is int and 0<=row-history_length<len(forecast):end=row-history_length
    elif (failure.get('reason')=='native_damage'and 'max_world_x'in failure
            and isfinite(failure['max_world_x'])):
        reachable=[i for i,row in enumerate(forecast)
                   if row['job']['before']['position']['x']<=failure['max_world_x']+1e-5]
        event=failure['event']['row_index']-history_length
        end=max(event,max(reachable,default=-1))
    return tuple(row['action']for row in forecast[:end+1])


def record_margin_feedback(cache,forecast,history_length,audit):
    failure=audit.get('failure',{});event=failure.get('perturbed_event')or failure.get('event',{})
    index=event.get('row_index',-1)-history_length
    if failure.get('reason')not in('native_damage','operation_prerequisite_mismatch','operation_effect_mismatch')or failure.get('shift_ms')not in(-40,40)or not 0<=index<len(forecast):return
    row=forecast[index]
    feedback=dict(before=tuple((r['job']['before']['episodeFrame'],r['action'])for r in forecast[:index]if r['action']!='none'),
                  frame=row['job']['before']['episodeFrame'],action=row['action'],shift=1 if failure['shift_ms']>0 else-1)
    if all(row['job'][side].get('physics')for side in ('before','after')):
        feedback['native_kind']=tuple(row['job'][side]['physics'].split(':')[0].lower()for side in ('before','after'))
    if feedback not in cache.margin_feedback:cache.margin_feedback.append(feedback)


def continuation_feedback(cache,path):
    """Carry soft scores only along the actual committed native prefix."""
    committed=tuple((r['job']['before']['episodeFrame'],r['action'])for r in path if r['action']!='none')
    frame=path[-1]['job']['after']['episodeFrame'];result=[]
    for feedback in cache.margin_feedback:
        if feedback['frame']<frame or tuple(feedback['before'][:len(committed)])!=committed:continue
        item=dict(feedback,before=tuple(feedback['before'][len(committed):]))
        if item not in result:result.append(item)
    return result[-96:]


def window(gate,*,searcher,history,initial_point,initial_state,board_code,**kwargs):
    cache=PrefixCache();result=None
    try:
        result=_window(gate,searcher=searcher,history=history,initial_point=initial_point,
                       initial_state=initial_state,board_code=board_code,tree_cache=cache,**kwargs)
        result['stats']['retained_prefix_points']=len(cache.points)
        return result
    finally:
        keep={r['point']for r in result['path']}if result and result['found']else set()
        cache.close(gate,keep)


def _window(gate,*,searcher,history,initial_point,initial_state,board_code,tree_cache,**kwargs):
    forbidden=set(kwargs.pop('forbidden_prefixes',()))
    budget=kwargs.pop('max_trials',1200)
    root=kwargs.pop('root_point',None)
    audits=[];used=0;proposal_stats=[];inherited_feedback=0
    def finish(result):
        stats=result['stats']
        for name in ('seconds','rejected_damage','rejected_invalid_interval','rejected_no_effect','prefix_cache_hits',
                     'decision_cache_hits','timing_spacing_pruned','transport_spacing_pruned','redundant_restores_skipped',
                     'snapshots_created','snapshots_avoided'):
            stats[name]=sum(s.get(name,0)for s in proposal_stats)
        stats['restores_ms']=[v for s in proposal_stats for v in s.get('restores_ms',[])]
        stats['native_decisions']=[v for s in proposal_stats for v in s.get('native_decisions',[])]
        stats['trials']=stats['total_candidate_trials']=used
        stats['proposals']=len(proposal_stats)
        stats['inherited_margin_feedback']=inherited_feedback
        result['timing_attempts']=audits
        return result
    hint=getattr(gate,'_arena_native_continuation',None)
    matched=bool(hint and history and hint['start']is kwargs['start']
                 and hint['history_length']==len(history)and hint['point']==history[-1]['point'])
    kwargs['warm_start']=hint['actions']if matched else()
    if matched:
        tree_cache.margin_feedback.extend(dict(f)for f in hint.get('margin_feedback',()))
        inherited_feedback=len(tree_cache.margin_feedback)
    gate._arena_native_continuation=None
    previous=next((r['job']['before']['episodeFrame']for r in reversed(history)if r['action']!='none'),None)
    previous_time=next((r['job']['before'].get('time')for r in reversed(history)if r['action']!='none'),None)
    while used<budget:
        result=searcher(gate,**kwargs,max_trials=budget-used,root_point=root,
                        forbidden_prefixes=forbidden,guided=True,retain_forecast=True,last_input_frame=previous,
                        last_input_time=previous_time,input_history=history,tree_cache=tree_cache)
        root=result['root'];used+=result['stats']['trials']
        proposal_stats.append(dict(result['stats']))
        if not result['found']:
            return finish(result)
        path=result['path'];forecast=result.pop('forecast_path')
        combined=history+forecast
        selected={len(history)+i for i,row in enumerate(path)if row['action']!='none'}
        end_frame=forecast[-1]['job']['after']['episodeFrame']
        selected.update(len(history)+i for i,row in enumerate(forecast)
                        if i>=len(path)and row['action']!='none'
                        and (row['job']['before']['time']+.04+1/60<forecast[-1]['job']['after']['time']
                             if 'time'in row['job']['before']and 'time'in forecast[-1]['job']['after']
                             else row['job']['before']['episodeFrame']+2<end_frame))
        def progress(check):
            print(f'独立80ms窗口: 操作{check["event"]} 偏移{check["shift_ms"]}ms 通过={check["passed"]}',flush=True)
        audit=(verify(gate,combined,initial_point=initial_point,initial_state=initial_state,
                      start=kwargs['start'],board_code=board_code,selected_rows=selected,on_result=progress)
               if selected else dict(passed=True,operations=0,window_ms=80,checks=[]))
        audits.append(audit)
        if audit['passed']:
            committed={r['point']for r in path}
            for point in {r['point']for r in forecast}-committed-tree_cache.points:gate.drop(point)
            gate._arena_native_continuation=dict(start=kwargs['start'],
                history_length=len(history)+len(path),point=path[-1]['point'],
                actions=tuple(row['action']for row in forecast[len(path):]),
                margin_feedback=continuation_feedback(tree_cache,path))
            return finish(result)
        prefix=rejected_prefix(forecast,len(history),audit)
        record_margin_feedback(tree_cache,forecast,len(history),audit)
        audit['rejected_forecast_prefix']=list(prefix)
        forbidden.add(prefix)
        gate.restore(root)
        for point in {r['point']for r in forecast}-tree_cache.points:gate.drop(point)
    return finish(dict(found=False,root=root,trials=[],path=[],
                reason='Native proposal budget exhausted while repairing operation timing windows',
                stats={}))
