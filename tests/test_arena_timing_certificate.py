from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_timing_certificate import valid


def certificate():
    return dict(passed=True,window_ms=80,independent=True,scope='whole_board_suffix',
        covers_start_frame=10,covers_end_frame=100,operations=2,offsets_ms=[-40,-20,0,20,40],
        checks=[dict(event=i,shift_ms=s,passed=True)for i in range(2)for s in(-40,-20,0,20,40)])


def test_every_operation_needs_all_five_independent_offsets_and_the_original_entry():
    c=certificate();assert valid(c,10,100,2)
    bad=deepcopy(c);bad['checks'][-1]=deepcopy(bad['checks'][0])
    assert not valid(bad,10,100,2)
    bad=deepcopy(c);bad['checks'].pop();assert not valid(bad,10,100,2)
    bad=deepcopy(c);bad['independent']=False;assert not valid(bad,10,100,2)
    bad=deepcopy(c);bad['scope']='native_forecast_suffix';assert not valid(bad,10,100,2)
    assert not valid(c,11,100,2)and not valid(c,10,100,3)
