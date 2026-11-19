"""A passing timing probe must not let a corrupted restored entry start search."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab'))
import clock_audit


@pytest.mark.parametrize('corrupt_restore',[False,True])
def test_admission_requires_restoring_the_original_entry(tmp_path,monkeypatch,corrupt_restore):
    class Gate:
        def __init__(self):
            self.current=dict(health=5000,time=1.,episodeFrame=0,physics='runOnLine: 1')
            self.points={};self.serial=0
        def call(self,operation,**kwargs):
            return deepcopy(self.current)if operation=='state'else dict(map=42,stage_index=1)
        def snapshot(self):
            self.serial+=1;self.points[self.serial]=deepcopy(self.current)
            return dict(result=dict(id=self.serial))
        def rebase(self):return self.snapshot()
        def step(self,ticks,action):
            before=deepcopy(self.current);self.current['episodeFrame']+=ticks
            return dict(before=before,after=deepcopy(self.current))
        def restore(self,point):
            self.current=deepcopy(self.points[point])
            if corrupt_restore:self.current['episodeFrame']+=1
        def drop(self,point):del self.points[point]
    monkeypatch.setattr(clock_audit,'install_observer',lambda gate:None)
    monkeypatch.setattr(clock_audit,'install_clock',lambda gate:None)
    monkeypatch.setattr(clock_audit,'verify',lambda *a,**kw:dict(passed=True))
    gate=Gate();output=tmp_path/'admission'
    run=lambda:clock_audit.run(gate,{},output,lambda *a,**kw:None,lambda *a:None)
    if corrupt_restore:
        with pytest.raises(RuntimeError,match='did not restore its original entry'):run()
    else:
        assert run()['passed']
    report=json.loads((output/'report.json').read_text())
    assert report['passed']is(not corrupt_restore)
    assert report['root_restored']is(not corrupt_restore)
    assert list(gate.points)==[1]
