"""Posthoc native key receipts: match causal intervals, never input ordinals.

Evaluation only. Dropped keys or skipped evaluator polls can make pairing
ambiguous; these cases must not become fabricated latency samples.
"""
import math


class KeyReceiptMatcher:
    def __init__(self, initial_time):
        self.initial_time = float(initial_time)
        self.previous = {}
        self.seen = set()

    def match(self, key, receipt, actions):
        identity = key, receipt['count'], receipt['time']
        if identity in self.seen:
            return None, None
        self.seen.add(identity)
        stamp = receipt['time']
        previous_time, previous_count = self.previous.get(key, (self.initial_time, 0))
        result = dict(key=key, native_count=receipt['count'], native_time=stamp,
                      interval_start=previous_time, candidate_key_counts=[])
        if not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp <= previous_time:
            return None, dict(result, status='invalid_native_order')
        self.previous[key] = stamp, receipt['count']
        candidates = [a for a in actions if a.get('key') == key
                      and isinstance(a.get('enqueued_time'), (int, float))
                      and previous_time < a['enqueued_time'] <= stamp]
        result['candidate_key_counts'] = [a['key_count'] for a in candidates]
        # A latest-only sample can skip earlier receipts. Even a single visible
        # candidate cannot establish pairing when native count skipped events.
        if receipt['count'] != previous_count + 1:
            return None, dict(result, status='skipped_native_receipts')
        if len(candidates) != 1:
            return None, dict(result, status='ambiguous' if candidates else 'unmatched')
        return candidates[0], dict(result, status='matched', key_count=candidates[0]['key_count'])
