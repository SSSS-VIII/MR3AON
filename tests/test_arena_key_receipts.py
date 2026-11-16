from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_key_receipts import KeyReceiptMatcher


def action(count, time, key='down'):
    return dict(key=key,key_count=count,enqueued_time=time)


def test_dropped_key_does_not_shift_all_later_latency_pairs():
    matcher=KeyReceiptMatcher(0)
    actions=[action(1,1),action(2,2),action(3,3),action(4,4)]
    assert matcher.match('down',dict(count=1,time=1.02),actions)[0]is actions[0]
    event,row=matcher.match('down',dict(count=2,time=3.02),actions)
    assert event is None and row['status']=='ambiguous'
    event,row=matcher.match('down',dict(count=3,time=4.02),actions)
    assert event is actions[3]and row['native_count']==3 and row['key_count']==4


def test_sampling_gap_is_explicit_and_later_interval_can_recover():
    matcher=KeyReceiptMatcher(0);actions=[action(i,float(i))for i in range(1,5)]
    event,row=matcher.match('down',dict(count=3,time=3.02),actions)
    assert event is None and row['status']=='skipped_native_receipts'
    assert matcher.match('down',dict(count=4,time=4.02),actions)[0]is actions[3]


def test_unique_long_delay_is_retained_without_a_latency_cutoff():
    event=action(1,1)
    assert KeyReceiptMatcher(0).match('down',dict(count=1,time=3),[event])[0]is event


def test_duplicate_and_out_of_order_receipts_never_add_samples():
    matcher=KeyReceiptMatcher(0);event=action(1,1);receipt=dict(count=1,time=1.02)
    assert matcher.match('down',receipt,[event])[0]is event
    assert matcher.match('down',receipt,[event])==(None,None)
    assert matcher.match('down',dict(count=2,time=.9),[event])[1]['status']=='invalid_native_order'


def test_keys_are_independent_and_future_submissions_cannot_match():
    matcher=KeyReceiptMatcher(0);actions=[action(1,1,'jump'),action(1,2)]
    assert matcher.match('down',dict(count=1,time=1.1),actions)[1]['status']=='unmatched'
    assert matcher.match('jump',dict(count=1,time=1.2),actions)[0]is actions[0]
