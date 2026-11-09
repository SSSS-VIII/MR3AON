"""Offline failure review must align device clocks, never host read times."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_failure_audit import review


def test_failure_review_uses_native_monotonic_clock_and_retains_preceding_input(tmp_path):
    vision=[dict(time=10.,elapsed=0.,frame=0,phase='rope_above',action=None,reason='clear',jumps=0),
            dict(time=10.2,elapsed=.2,frame=1,phase='flip_up',action='jump',reason='flip',jumps=0),
            dict(time=10.3,elapsed=.3,frame=2,phase='rope_below',action=None,reason='clear',jumps=0)]
    actual=[dict(monotonic=10.,elapsed=500.,physics='runOnLine: 1',damage=0),
            dict(monotonic=10.3,elapsed=900.,physics='runOnLineDown: 2',damage=120)]
    for name,rows in [('vision',vision),('evaluation',actual)]:
        (tmp_path/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n'for r in rows))
    (tmp_path/'report.json').write_text(json.dumps(dict(status='passed_with_damage',final={'damage':120})))
    result=review(tmp_path)
    assert result['phases']==dict(samples=2,matched=2)
    assert result['hits'][0]['frame']==2
    assert result['hits'][0]['alignment_ms']==0
    assert result['hits'][0]['inputs'][0]['t']==.2
