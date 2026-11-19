"""Independent single-operation timing tests using retained original VM points.

Total window is 80 ms, sampled at -40/+40 ms on original 20 ms ticks.
Only the selected key moves. Subsequent keys keep their nominal board-X
targets; a preceding key's timing offset is never added to the next key.
"""
import time
from arena_fixed_goal import exit_kind
from arena_checkpoint_errors import NativeIntervalError

SHIFTS=(-2,2)


def events(rows):
    return [dict(index=i,row_index=j,tick=r['job']['before']['episodeFrame'],
                 x=r['job']['before']['position']['x'],action=r['action'])
            for i,(j,r)in enumerate((j,r)for j,r in enumerate(rows)if r['action']!='none')]


def verify(gate,rows,*,initial_point,initial_state,start,board_code,selected_rows=None,
           whole_board=False,on_result=None):
    keys=events(rows)
    selected=[e for e in keys if selected_rows is None or e['row_index']in selected_rows]
    priority=getattr(gate,'_arena_timing_priority',None)
    if priority is None:
        priority={};gate._arena_timing_priority=priority
    def risk(event,shift):
        return priority.get((initial_point,event['tick'],event['action'],shift),0)
    selected.sort(key=lambda event:-sum(risk(event,s)for s in SHIFTS))
    end_tick=rows[-1]['job']['after']['episodeFrame']
    anchors=[(initial_state['episodeFrame'],initial_point,initial_state)]
    anchors.extend((r['job']['after']['episodeFrame'],r['point'],r['job']['after'])for r in rows)
    report=dict(passed=False,window_ms=80,offsets_ms=[-40,40],sampling='endpoints',
                independent=True,subsequent_keys='unchanged nominal world-X targets',
                scope='whole_board_suffix'if whole_board else'native_forecast_suffix',
                covers_start_frame=initial_state['episodeFrame'],covers_end_frame=end_tick,
                checks=[],operations=len(selected),started=time.monotonic())
    park=gate.snapshot()['result']['id']
    try:
        for event in selected:
            before=[a for a in anchors if a[0]<=event['tick']-2]
            if not before:
                report['failure']=dict(event=event,reason='earlier_side_precedes_retained_entry')
                return report
            anchor=max(before,key=lambda a:a[0])
            previous=keys[event['index']-1]if event['index']else None
            following=keys[event['index']+1]if event['index']+1<len(keys)else None
            for shift in sorted(SHIFTS,key=lambda s:-risk(event,s)):
                result=dict(event=event['index'],row_index=event['row_index'],shift_ticks=shift,
                            shift_ms=shift*20,anchor_frame=anchor[0],target_frame=event['tick']+shift)
                if (previous and event['tick']+shift<=previous['tick']or
                        following and event['tick']+shift>=following['tick']):
                    result.update(passed=False,reason='operation_order_changes')
                else:
                    result['restore_ms']=gate.restore(anchor[1])['ms']
                    current=gate.call('state')
                    if current!=anchor[2]:raise RuntimeError('Timing audit did not restore its nominal checkpoint')
                    try:result.update(_branch(gate,keys,event,shift,current,end_tick,start,board_code,whole_board))
                    except NativeIntervalError as error:
                        result.update(passed=False,reason='native_interval_invalid',error=str(error))
                report['checks'].append(result)
                if on_result:on_result(result)
                if not result['passed']:
                    identity=(initial_point,event['tick'],event['action'],shift)
                    priority[identity]=priority.get(identity,0)+1
                    report['failure']=dict(result,event=event)
                    return report
        report['passed']=True
        return report
    finally:
        report['seconds']=time.monotonic()-report.pop('started')
        report['park_restore_ms']=gate.restore(park)['ms']
        gate.drop(park)


def _branch(gate,keys,event,shift,current,end_tick,start,board_code,whole_board):
    remaining=[k for k in keys if k['tick']>=current['episodeFrame']]
    cursor=0;actions=[];steps=0;furthest=current['position']['x']
    limit=end_tick+(100 if whole_board else 0)
    while current['episodeFrame']<limit:
        before=current
        key=remaining[cursor]if cursor<len(remaining)else None
        moved=key is not None and key['index']==event['index']
        due=bool(key and (current['episodeFrame']>=event['tick']+shift if moved else
                         current['position']['x']>=key['x']-1e-5))
        if due:
            action=key['action'];ticks=1
            if moved and current['episodeFrame']!=event['tick']+shift:
                return dict(passed=False,reason='perturbed_tick_not_reached_exactly',actual=current,actions=actions)
            actions.append(dict(index=key['index'],action=action,frame=current['episodeFrame'],
                                x=current['position']['x'],target_x=key['x'],
                                before_physics=current.get('physics'),before_y=current['position'].get('y')))
            cursor+=1
        else:
            action='none'
            if moved:ticks=max(1,min(5,event['tick']+shift-current['episodeFrame']))
            elif key:
                speed=max(40,current.get('speed',18.5)*1.5)
                ticks=max(1,min(5,int((key['x']-current['position']['x'])/(speed*.02))-1))
            else:ticks=min(5,limit-current['episodeFrame'])
            ticks=min(ticks,limit-current['episodeFrame'])
        job=gate.step(ticks,action);current=job['after'];steps+=1
        if due:
            actions[-1].update(after_physics=current.get('physics'),after_y=current['position'].get('y'))
        furthest=max(furthest,before['position']['x'],current['position']['x'],
                     *(s['position']['x']for s in job.get('samples',[])))
        if job.get('terminated')or current['health']!=start['health']:
            return dict(passed=False,reason='native_damage',before=before,actual=current,
                        actions=actions,steps=steps,max_world_x=furthest)
        board=gate.call('exec',code=board_code)
        if exit_kind(start['board'],board):
            return dict(passed=cursor==len(remaining),reason='native_exit',actual=current,actions=actions,steps=steps)
    passed=not whole_board and cursor==len(remaining)
    return dict(passed=passed,reason='forecast_end'if passed else'original_targets_not_completed',
                actual=current,actions=actions,steps=steps)
