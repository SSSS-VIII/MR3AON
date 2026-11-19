"""Measured endpoint tests; local screens are separate from transfer certificates."""
from pathlib import Path
import time

from arena_action_contract import contract
from arena_checkpoint_errors import NativeIntervalError
from endpoint_rollout import Rollouts,scenarios

SHIFTS=(-40,40)


def install_clock(gate):
    from collector import install_lua
    install_lua(gate,(Path(__file__).parent/'clock_step.lua').read_text())


def events(rows):
    return [dict(index=i,row_index=j,tick=r['job']['before']['episodeFrame'],
                 time=r['job']['before']['time'],x=r['job']['before']['position']['x'],action=r['action'],
                 contract=contract(r['job']['before']['physics'],r['action'],r['job']['after']['physics']))
            for i,(j,r)in enumerate((j,r)for j,r in enumerate(rows)if r['action']!='none')]


def verify(gate,rows,*,initial_point,initial_state,start,board_code,selected_rows=None,
           whole_board=False,on_result=None,full_suite=True):
    keys=events(rows)
    selected=[e for e in keys if selected_rows is None or e['row_index']in selected_rows]
    point,state=initial_point,initial_state
    if not whole_board and selected:
        # Local proposal screening is explicitly not a transfer certificate.
        # Include the full render-quantization radius before the earliest key.
        threshold=min(e['time']for e in selected)-.04-1/60
        anchors=[(initial_state['time'],initial_point,initial_state)]
        anchors.extend((r['job']['after']['time'],r['point'],r['job']['after'])for r in rows
                       if r.get('point')is not None)
        available=[a for a in anchors if a[0]<=threshold+1e-5]
        if available:_,point,state=max(available,key=lambda a:a[0])
    remaining=[key for key in keys if key['time']>=state['time']-1e-5]
    indices=[key['index']for key in selected]
    plans=scenarios(indices,pairs=whole_board and full_suite)
    if not full_suite:
        plans=[p for p in plans if p['kind']in('nominal','continuous')]
        # Deduplication may have assigned a continuous one-key plan to single.
        wanted={tuple([s]*len(indices))for s in(-40,40)}
        wanted.update(tuple(s if i%2==0 else-s for i in range(len(indices)))for s in(-40,40))
        plans=[p for p in scenarios(indices,pairs=False)if not any(p['schedule'])or tuple(p['schedule'])in wanted]
    report=dict(version=2,passed=False,window_ms=80,offsets_ms=[-40,40],sampling='endpoints',
        clock='Unity.Time.time',timing_reference='each reachable prefix native world-X crossing',
        quantization_ms=1000/60,independent=True,semantic_checks=True,
        prefix_coverage='single_adjacent_continuous'if full_suite else'continuous',
        exhaustive=False,scope='whole_board_suffix'if whole_board else'native_forecast_suffix',
        covers_start_frame=initial_state['episodeFrame'],covers_end_frame=rows[-1]['job']['after']['episodeFrame'],
        operations=len(selected),event_indices=indices,checks=[],started=time.monotonic())
    park=gate.snapshot()['result']['id'];runner=None
    try:
        if any(b['x']<a['x']for a,b in zip(remaining,remaining[1:])):
            report['failure']=dict(reason='nonmonotone_operation_targets',event=remaining[0])
            return report
        runner=Rollouts(gate,remaining,point=point,state=state,start=start,board_code=board_code,
                        end_state=rows[-1]['job']['after'],whole_board=whole_board)
        for number,plan in enumerate(plans):
            try:result=runner.run(plan)
            except NativeIntervalError as error:
                result=dict(passed=False,reason='native_interval_invalid',error=str(error),event=remaining[0]if remaining else None)
            failed=result.get('event')
            changed=[key for key in remaining if plan['offsets'].get(key['index'])]
            display=failed or(changed[0]if changed else(remaining[0]if remaining else None))
            result.update(scenario=number,kind=plan['kind'],schedule=plan['schedule'])
            if result['passed']:
                result.update(event=display['index']if display else-1,
                              shift_ms=plan['offsets'].get(display['index'],0)if display else 0)
            if not result['passed']:
                cause=next((k for k in changed if not failed or k['index']<=failed['index']),None)
                if cause:
                    result.update(perturbed_event=cause,shift_ms=plan['offsets'][cause['index']],
                                  repair_row_index=cause['row_index'])
                    display=cause
            report['checks'].append(result)
            if on_result:
                on_result(dict(result,event=display['index']if display else-1,
                               shift_ms=result.get('shift_ms',0)))
            if not result['passed']:
                report['failure']=dict(result,event=failed or display)
                return report
        report['passed']=True
        return report
    finally:
        report['seconds']=time.monotonic()-report.pop('started')
        report['park_restore_ms']=gate.restore(park)['ms']
        if runner:runner.close()
        gate.drop(park)
