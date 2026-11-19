from copy import deepcopy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_timing_certificate import valid,schedules


def context(full=True):
    return dict(version=2,passed=True,window_ms=80,offsets_ms=[-40,40],sampling='endpoints',
        clock='Unity.Time.time',timing_reference='each reachable prefix native world-X crossing',
        independent=True,semantic_checks=True,exhaustive=False,scope='whole_board_suffix',
        prefix_coverage='single_adjacent_continuous'if full else'continuous',
        covers_start_frame=10,covers_end_frame=100,operations=2,event_indices=[0,1],
        checks=[dict(passed=True,reason='native_exit',schedule=list(p),actions=[dict(index=i,requested_shift_ms=s,
            nominal_crossing_time=1.,input_time=1.+s/1000*1.25,actual_shift_ms=s*1.25)
            for i,s in enumerate(p)])for p in sorted(schedules(2,full))])


def certificate():
    return dict(context(),reentries=[dict(seed=s,fresh_initialization=True,unprotected=True,
                                         validation=context(False))for s in(55201,55202)])


def test_requires_measured_offsets_real_prefix_scenarios_and_two_fresh_entries():
    c=certificate();assert valid(c,10,100,2)
    bad=deepcopy(c);bad['checks'].pop();assert not valid(bad,10,100,2)
    bad=deepcopy(c);bad['checks'][-1]=bad['checks'][0];assert not valid(bad,10,100,2)
    bad=deepcopy(c);bad['reentries'].pop();assert not valid(bad,10,100,2)
    bad=deepcopy(c);bad['reentries'][1]['seed']=55201;assert not valid(bad,10,100,2)
    bad=deepcopy(c);bad['reentries'][0]['unprotected']=False;assert not valid(bad,10,100,2)
    assert not valid(c,11,100,2)and not valid(c,10,100,3)


def test_counter_clock_and_old_passed_tables_cannot_be_promoted():
    c=certificate()
    for field,value in [('version',1),('clock','GameInfo._totalFrameCount'),('semantic_checks',False),('exhaustive',True)]:
        bad=deepcopy(c);bad[field]=value;assert not valid(bad,10,100,2)
    assert not valid(dict(passed=True,window_ms=80,independent=True,scope='whole_board_suffix',
        covers_start_frame=10,covers_end_frame=100,operations=2,offsets_ms=[-40,40],
        checks=[dict(event=i,shift_ms=s,passed=True)for i in(0,1)for s in(-40,40)]),10,100,2)


def test_each_requested_endpoint_needs_actual_clock_coverage_and_ordered_inputs():
    c=certificate()
    for value in(20.,float('nan'),100.):
        bad=deepcopy(c);a=next(a for r in bad['checks']for a in r['actions']if a['requested_shift_ms']==40)
        a.update(actual_shift_ms=value,input_time=1.+value/1000)
        assert not valid(bad,10,100,2)
    bad=deepcopy(c);bad['checks'][0]['actions'].reverse();assert not valid(bad,10,100,2)
    bad=deepcopy(c);bad['reentries'][1]['validation']['passed']=False;assert not valid(bad,10,100,2)
