"""Validate finite measured-clock evidence, never legacy counter certificates."""
from math import isfinite
from arena_input_transport import PROFILE, repeat_failure, transport_action

VERSION=3


def schedules(count,full=True):
    zero=(0,)*count;wanted={zero}
    if full:
        for i in range(count):
            for sign in(-40,40):
                row=list(zero);row[i]=sign;wanted.add(tuple(row))
        for i in range(count-1):
            for sign in(-40,40):
                row=list(zero);row[i]=sign;row[i+1]=-sign;wanted.add(tuple(row))
    wanted.update({(-40,)*count,(40,)*count})
    wanted.update(tuple(sign if i%2==0 else-sign for i in range(count))for sign in(-40,40))
    return wanted


def _context(certificate,count,full):
    if not(certificate.get('version')==VERSION and certificate.get('transport')==PROFILE and certificate.get('passed')is True
        and certificate.get('window_ms')==80 and certificate.get('offsets_ms')==[-40,40]
        and certificate.get('sampling')=='endpoints'and certificate.get('clock')=='Unity.Time.time'
        and certificate.get('timing_reference')=='each reachable prefix native world-X crossing'
        and certificate.get('independent')is True and certificate.get('semantic_checks')is True
        and certificate.get('exhaustive')is False and certificate.get('scope')=='whole_board_suffix'
        and certificate.get('prefix_coverage')==('single_adjacent_continuous'if full else'continuous')
        and certificate.get('operations')==count and certificate.get('event_indices')==list(range(count))):return False
    checks=certificate.get('checks',[]);expected=schedules(count,full)
    if len(checks)!=len(expected):return False
    seen=set()
    for check in checks:
        schedule=tuple(check.get('schedule',[]))
        if (check.get('passed')is not True or check.get('reason')!='native_exit'
                or schedule not in expected or schedule in seen):return False
        seen.add(schedule);actions=check.get('actions',[])
        if [a.get('index')for a in actions]!=list(range(count)):return False
        delivered=[]
        for action,shift in zip(actions,schedule):
            actual=action.get('actual_shift_ms');base=action.get('nominal_crossing_time');sent=action.get('input_time')
            if (action.get('requested_shift_ms')!=shift or not all(type(v)in(int,float)and isfinite(v)for v in(actual,base,sent))
                    or abs((sent-base)*1000-actual)>.03):return False
            if shift:
                if actual*shift<=0 or not 39.97<=abs(actual)<=56.70:return False
            elif abs(actual)>.03:return False
            if action.get('transport_action')not in('jump','down','slide'):return False
            try:kind=transport_action(action.get('action'),action.get('before_physics',''))
            except (ValueError,AttributeError):return False
            if kind!=action['transport_action']:return False
            if repeat_failure(delivered,action['transport_action'],sent):return False
            delivered.append(action)
    return seen==expected


def valid(certificate,start_frame,end_frame,operation_count):
    if not(_context(certificate,operation_count,True)
        and certificate.get('covers_start_frame')==start_frame
        and certificate.get('covers_end_frame')==end_frame):return False
    entries=certificate.get('reentries',[])
    return (len(entries)==2 and len({e.get('seed')for e in entries})==2
        and all(e.get('fresh_initialization')is True and e.get('unprotected')is True
                and _context(e.get('validation',{}),operation_count,False)for e in entries))
