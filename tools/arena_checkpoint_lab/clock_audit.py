"""Bounded native admission check before a new search epoch starts."""
import json
from pathlib import Path

from collector import install_observer
from timing_margin import install_clock,verify
from search import BOARD


def run(gate,case,output,initialize,progress):
    """A safe head-of-50022 jump must pass both measured endpoints first.

    This independent forward fixture is discarded using full VM restores.
    It is not a route result, search rollback by replay, or a visual success.
    """
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    initialize(gate,case,progress,seed=55200)
    install_observer(gate);install_clock(gate)
    initial=gate.call('state');board=gate.call('exec',code=BOARD)
    root=gate.rebase()['result']['id'];rows=[]
    report=dict(passed=False,scope='safe-corridor native clock and action admission only',
                search_started=False,start=dict(state=initial,board=board))
    try:
        for i in range(12):
            action='jump'if i==3 else'none'
            job=gate.step(2 if i%2==0 else 3,action)
            if job['after']['health']!=5000:raise RuntimeError('Safe-corridor admission fixture took damage')
            rows.append(dict(job=job,action=action,ticks=2 if i%2==0 else 3,
                             point=gate.snapshot()['result']['id']))
        validation=verify(gate,rows,initial_point=root,initial_state=initial,
            start=dict(health=5000,state=initial,board=board),board_code=BOARD,
            on_result=lambda c:progress(dict(phase='clock_admission',scenario=c['scenario'],passed=c['passed'])))
        report['validation']=validation
        if not validation['passed']:raise RuntimeError('Native clock admission rejected a safe original jump')
        report['passed']=True
        return report
    except BaseException as error:
        report['error']=repr(error);raise
    finally:
        gate.restore(root)
        report['root_restored']=gate.call('state')==initial
        for point in list(gate.points):
            if point!=root:gate.drop(point)
        (output/'report.json').write_text(json.dumps(report,indent=2))
