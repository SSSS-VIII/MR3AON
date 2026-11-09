#!/usr/bin/env python3
"""Join saved visual estimates with native evaluation for offline failure review.

No client connection or policy import: privileged labels cannot select inputs.
Alignment uses Android monotonic clocks, not host file-read/elapsed timestamps.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

PHASES={'runOnLine':'rope_above','runOnLineDown':'rope_below',
        'rollToLineDown':'flip_down','rollToLineOn':'flip_up','runOnGround':'ground',
        'jump':'jump1_rising','fall':'jump1_falling','jump2':'jump2_rising','fall2':'jump2_falling'}


def review(folder):
    vision=[json.loads(s)for s in(folder/'vision.jsonl').read_text().splitlines()]
    evaluation=[json.loads(s)for s in(folder/'evaluation.jsonl').read_text().splitlines()]
    report=json.loads((folder/'report.json').read_text())
    actions=[r['time']for r in vision if r.get('action')]
    phases=Counter();confusion=Counter();hits=[];before=0
    for actual in evaluation:
        stamp=actual['monotonic'];nearest=min(vision,key=lambda r:abs(r['time']-stamp))
        native=PHASES.get(actual['physics'].split(':')[0])
        if native and abs(nearest['time']-stamp)<=.045:
            # Native telemetry is slower than images; exclude immediate input
            # transitions from the stable-state diagnostic, retain hit windows.
            if not any(abs(stamp-t)<.09 for t in actions):
                phases['samples']+=1
                phases['matched']+=native==nearest['phase']
                if native!=nearest['phase']:
                    confusion[native+' -> '+nearest['phase']]+=1
        damage=actual.get('damage',0)
        if damage>before:
            preceding=[r for r in vision if stamp-.6<=r['time']<=stamp]
            inputs=[dict(t=r['elapsed'],action=r['action'],phase=r['phase'],jumps=r['jumps'],
                         reason=r['reason'])for r in preceding if r.get('action')]
            hits.append(dict(t=nearest['elapsed'],frame=nearest['frame'],increment=damage-before,
                native=actual['physics'],estimated=nearest['phase'],reason=nearest['reason'],
                inputs=inputs,alignment_ms=round((nearest['time']-stamp)*1000,3)))
        before=damage
    return dict(run=str(folder),status=report['status'],damage=report['final']['damage'],
                phases=dict(phases),confusion=dict(confusion.most_common()),hits=hits,
                scope='Offline telemetry alignment; transition frames excluded from phase metric; not policy input')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=review(a.run)
    with a.output.open('x')as out:out.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
