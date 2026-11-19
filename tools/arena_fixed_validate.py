"""Grade recorded hybrid runs after execution; never an input to the actor."""
import argparse
import bisect
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


def percentile(values, fraction):
    if not values:
        return None
    ordered=sorted(values)
    return ordered[min(len(ordered)-1, math.ceil(fraction*len(ordered))-1)]


def sequence_review(estimates,actions,program,key):
    """Require every tape event to have one acknowledged, ordered submission."""
    recorded=[]
    for row in estimates:
        control=row.get('fixed_route',{});commit=row.get('action_commit')or{}
        if (not row.get('action')or control.get('mode')!='fixed'
                or not row.get('reason','').startswith('fixed_route_')):continue
        recorded.append(dict(index=control.get('event'),action=row['action'],
            time=commit.get('committed_time'),key=control.get('board',{}).get('key')))
    fixed=[a for a in actions if a.get('reason','').startswith('fixed_route_')]
    expected=program['events']
    ordered=([r['index']for r in recorded]==list(range(len(expected)))
             and all(r['action']==e['action']and r['key']==key
                     and type(r['time'])in(int,float)and math.isfinite(r['time'])
                     for r,e in zip(recorded,expected)))
    matched=(Counter((r['time'],r['action'])for r in recorded)==
             Counter((a.get('committed_time'),a.get('action'))for a in fixed))
    off_tape=[a for a in actions if not a.get('reason','').startswith('fixed_route_')]
    locked=any(row.get('fixed_route',{}).get('mode')=='fixed'
               and row.get('fixed_route',{}).get('board',{}).get('key')==key for row in estimates)
    return dict(complete=bool(ordered and matched and len(fixed)==len(expected)
                              and not off_tape and (expected or locked)),
                expected=len(expected),recorded_indices=[r['index']for r in recorded],
                acknowledged_fixed_keys=len(fixed),ordered=ordered,
                report_matches_frames=matched,off_tape_keys=len(off_tape))


def review(folder, case, program):
    folder=Path(folder)
    report=json.loads((folder/'report.json').read_text())
    setup=json.loads((folder/'setup.json').read_text())
    native=[json.loads(line) for line in (folder/'evaluation.jsonl').read_text().splitlines()]
    native=sorted({row['monotonic']:row for row in native}.values(),key=lambda row:row['monotonic'])
    times=[row['monotonic'] for row in native]
    estimates=[json.loads(line) for line in (folder/'vision.jsonl').read_text().splitlines()]
    target=(case['map'],case['slot']-1,case['stage'])
    seen=identified=localized=wrong_identity=control_frames=control_localized=control_identified=0
    errors=[]
    for estimate in estimates:
        timestamp=estimate.get('time')
        if timestamp is None:
            continue
        index=bisect.bisect_right(times,timestamp)
        if not 0 < index < len(native):
            continue
        a,b=native[index-1],native[index]
        def context(row):return row['map'],row['stageIndex'],row['stageID']
        if context(a)!=target or context(b)!=target or b['monotonic']-a['monotonic']>.3:
            continue
        seen+=1
        fraction=(timestamp-a['monotonic'])/(b['monotonic']-a['monotonic'])
        x=(a['x']+(b['x']-a['x'])*fraction-a['stageStartX']
           if a.get('stageStartX') is not None and a.get('stageStartX')==b.get('stageStartX')else None)
        control_start=(program['events'][0]['x']-2 if program['events']
                       and 'x'in program['events'][0]else program.get('entry_x',0))
        in_control_span=x is not None and x>=control_start
        control_frames+=int(in_control_span)
        board=estimate.get('fixed_route',{}).get('board',{})
        identity=board.get('identity')
        if identity is not None:
            if tuple(identity)==(case['level'],case['map'],case['slot'],case['stage']):
                identified+=1
                control_identified+=int(in_control_span)
            else:
                wrong_identity+=1
        if not board.get('localized'):
            continue
        localized+=1
        control_localized+=int(in_control_span)
        if a.get('stageStartX') is None or a.get('stageStartX')!=b.get('stageStartX'):
            continue
        errors.append(abs(board['progress_x']-x))
    selection_ok=(setup['level']==case['level'] and setup['map']==case['map']
                  and setup['start']==case['slot']
                  and setup.get('goal_stage_index')==case['slot']
                  and setup.get('pins',{}).get(str(case['slot']))==case['stage'])
    # Require actual fixed execution. Merely loading a library, or passing
    # under the old reactive policy, does not validate a fixed input program.
    fixed_keys=sum(a.get('reason','').startswith('fixed_route_')for a in report['actions'])
    sequence=sequence_review(estimates,report['actions'],program,case['key'])
    executed=sequence['complete']
    expected_keys=Counter('jump'if e['action']=='jump'else'down'for e in program['events'])
    received=report['final'].get('keys',{})
    native_keys_match=all(type(received.get(key))is int and received[key]==expected_keys[key]
                          for key in('jump','down'))
    detector_verified=bool(seen>=20 and control_frames>=20 and control_identified/control_frames>=.95
                           and control_localized/control_frames>=.95
                           and wrong_identity==0 and len(errors)>=20 and percentile(errors,.95)<=.5)
    final=report['final']
    exited=(final['map']==case['map'] and final['stageIndex']>=case['slot']
            or final['map']!=case['map'] and setup['initial'].get('stageCount')==case['slot'])
    if case.get('loop'):
        initial=setup['initial']
        exited=bool(final['map']==case['map'] and final.get('stageStartX')is not None
                    and initial.get('stageStartX')is not None
                    and final['stageStartX']>initial['stageStartX']+.01
                    and final.get('stageInstance')is not None
                    and final['stageInstance']!=initial.get('stageInstance'))
    target_samples=[row for row in native if (row['map'],row['stageIndex'],row['stageID'])==target]
    unprotected=bool(setup['initial'].get('god')is False and setup['initial'].get('health')==5000
        and target_samples and all(row.get('god')is False for row in target_samples))
    live_verified=bool(selection_ok and detector_verified and executed and exited and unprotected and native_keys_match
                       and setup.get('fixed_route_assets') and not final.get('god',True)
                       and report['status']=='passed' and not report['had_damage']
                       and not report.get('evaluation_error') and report['final']['health']>0
                       and report['final'].get('damage',0)==0)
    result=dict(schema=1,key=case['key'],source=str(folder),
                source_sha256=hashlib.sha256((folder/'report.json').read_bytes()).hexdigest(),
                runtime_assets=setup.get('fixed_route_assets'), selection_verified=selection_ok,
                detector_verified=detector_verified,live_runner_verified=live_verified,
                native_grade='Post-run evaluation only; never supplied to the policy',
                sampled_frames=seen,identified_frames=identified,localized_frames=localized,
                control_frames=control_frames,control_localized_frames=control_localized,
                control_identified_frames=control_identified,
                incorrect_identity_frames=wrong_identity,progress_samples=len(errors),
                progress_error_m=dict(median=percentile(errors,.5),p95=percentile(errors,.95),
                                      max=max(errors)if errors else None),
                progress_grade='Interpolated native samples; not exact per-frame ground truth',
                fixed_keys=fixed_keys,fixed_sequence=sequence,unprotected_samples=unprotected,
                native_key_totals_match=native_keys_match,
                status=report['status'],had_damage=report['had_damage'])
    own_context=folder/'fixed-start-context.json'
    if own_context.exists():
        result['initial_context']=json.loads(own_context.read_text())
        result['recognition_scope']='Own requested starting level/slot; map, variant and subsequent progress are visual'
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--queue',type=Path,required=True)
    p.add_argument('--programs',type=Path,required=True)
    p.add_argument('--case',required=True)
    p.add_argument('--run',type=Path,required=True)
    args=p.parse_args()
    inventory=json.loads((args.queue/'inventory.json').read_text())
    case=next(c for c in inventory['contexts']if c['key']==args.case)
    program=json.loads(args.programs.read_text())['programs'][args.case]
    result=review(args.run,case,program)
    output=args.queue/'validation'/args.case
    output.mkdir(parents=True,exist_ok=True)
    (output/(result['source_sha256']+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
