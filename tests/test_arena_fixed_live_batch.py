import json
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_fixed_live_batch as batch


def test_test_ledger_is_per_seed_and_exact_runtime_and_code_version(tmp_path,monkeypatch):
    monkeypatch.setattr(batch,'ROOT',tmp_path)
    (tmp_path/'tools').mkdir();(tmp_path/'arena').mkdir()
    source=tmp_path/'tools/arena_fixed_policy.py';source.write_text('first')
    bundle=tmp_path/'bundle';bundle.mkdir()
    (bundle/'manifest.json').write_text('{}')
    programs=dict(schema=1,programs={'good':dict(native_passed=True),'unproven':dict(native_passed=False)})
    (bundle/'programs.json').write_text(json.dumps(programs))
    cases={'good':dict(level=5),'unproven':dict(level=5)}
    jobs=batch.pending(bundle,cases,{},[1,2])
    assert [j['key']for j in jobs]==['good','good']
    ledger={jobs[0]['job']:dict(status='graded'),jobs[1]['job']:dict(status='failed')}
    assert not batch.pending(bundle,cases,ledger,[1,2])
    (tmp_path/'tools/arena_file_history_audit.py').write_text('unrelated checkpoint experiment')
    assert not batch.pending(bundle,cases,ledger,[1,2])
    source.write_text('fixed input mapping')
    assert len(batch.pending(bundle,cases,ledger,[1,2]))==2
    newer=batch.pending(bundle,cases,{},[1,2])
    interrupted={j['job']:dict(status='interrupted')for j in newer}
    assert len(batch.pending(bundle,cases,interrupted,[1,2]))==2


def test_timeout_first_interrupts_the_actor_so_its_menu_cleanup_can_run(tmp_path,monkeypatch):
    events=[]
    class Child:
        calls=0
        def wait(self,timeout):
            self.calls+=1;events.append(('wait',timeout))
            if self.calls==1:raise subprocess.TimeoutExpired('actor',timeout)
            return 130
        def send_signal(self,value):events.append(('signal',value))
        def terminate(self):pytest.fail('graceful actor cleanup worked')
    monkeypatch.setattr(batch.subprocess,'Popen',lambda *_a,**_k:Child())
    with pytest.raises(subprocess.TimeoutExpired):batch.execute(['actor'],tmp_path/'actor.log')
    assert events==[('wait',480),('signal',signal.SIGINT),('wait',60)]
