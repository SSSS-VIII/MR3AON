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


def test_certified_routes_get_all_seeds_before_older_raw_candidates(tmp_path,monkeypatch):
    monkeypatch.setattr(batch,'fingerprint',lambda bundle,seed:str(seed))
    (tmp_path/'programs.json').write_text(json.dumps(dict(programs={
        'a':dict(native_passed=True),'b':dict(native_passed=True,timing_robust=True)})))
    cases={key:dict(level=5)for key in ('a','b')}
    jobs=batch.pending(tmp_path,cases,{},[1,2,3])
    assert [(j['key'],j['seed'])for j in jobs]==[('b',1),('b',2),('b',3),('a',1),('a',2),('a',3)]


def test_baselines_cover_step_uniform_and_real_clocks_once_per_frozen_route(tmp_path,monkeypatch):
    import hashlib
    monkeypatch.setattr(batch,'baseline_signature',lambda:'auditor-v1')
    route=tmp_path/'route.json';route.write_text(json.dumps(dict(start=dict(state=dict(seed=55)))))
    program=dict(native_passed=True,source=str(route),source_sha256=hashlib.sha256(route.read_bytes()).hexdigest())
    (tmp_path/'programs.json').write_text(json.dumps(dict(programs={'a':program})))
    jobs=batch.baseline_pending(tmp_path,{'a':{}},{})
    assert [(j['mode'],j['capture_fps'])for j in jobs]==[
        ('source_intervals',60),('continuous_ticks',60),('continuous_ticks',0)]
    ledger={j['job']:dict(status='graded',passed=False)for j in jobs}
    assert not batch.baseline_pending(tmp_path,{'a':{}},ledger)
    ledger[jobs[0]['job']]['status']='interrupted'
    assert len(batch.baseline_pending(tmp_path,{'a':{}},ledger))==1
    route.write_text('{}')
    with pytest.raises(RuntimeError,match='changed'):batch.baseline_pending(tmp_path,{'a':{}},ledger)


def test_stability_needs_every_repeat_and_new_actor_versions_cannot_inherit_old_passes(tmp_path,monkeypatch):
    monkeypatch.setattr(batch,'fingerprint',lambda b,s:'v1-'+str(s))
    (tmp_path/'programs.json').write_text(json.dumps(dict(programs={'a':dict(native_passed=True,timing_robust=True)})))
    cases={'a':dict(level=5)};jobs=batch.pending(tmp_path,cases,{},[1,2,3],repeats=3)
    assert len(jobs)==9 and len({j['job']for j in jobs})==9
    ledger={j['job']:dict(status='graded',grade=dict(live_runner_verified=True))for j in jobs}
    assert batch.stability(tmp_path,cases,ledger,[1,2,3],repeats=3)['cases']['a']['stable_no_damage']
    ledger[jobs[3]['job']]['grade']['live_runner_verified']=False
    assert not batch.stability(tmp_path,cases,ledger,[1,2,3],repeats=3)['cases']['a']['stable_no_damage']
    ledger.pop(jobs[3]['job'])
    state=batch.stability(tmp_path,cases,ledger,[1,2,3],repeats=3)['cases']['a']
    assert not state['stable_no_damage']and state['pending']==1
    monkeypatch.setattr(batch,'fingerprint',lambda b,s:'v2-'+str(s))
    assert batch.stability(tmp_path,cases,ledger,[1,2,3],repeats=3)['cases']['a']['pending']==9


def test_frozen_bank_config_is_explicit_and_cannot_follow_a_later_symlink(tmp_path):
    first=tmp_path/'bundles/first';second=tmp_path/'bundles/second';first.mkdir(parents=True);second.mkdir()
    current=tmp_path/'current';current.symlink_to(first)
    output=tmp_path/'checks';path=batch.frozen_config(current,output)
    current.unlink();current.symlink_to(second)
    assert json.loads(path.read_text())['bundle']==str(first.resolve())
    assert batch.frozen_config(current,output)!=path
    path.write_text('{}')
    with pytest.raises(RuntimeError,match='changed'):batch.frozen_config(first,output)


def test_fingerprint_tracks_native_evaluation_and_input_bridge_sources(tmp_path,monkeypatch):
    monkeypatch.setattr(batch,'ROOT',tmp_path)
    bundle=tmp_path/'bundle';bundle.mkdir()
    (bundle/'manifest.json').write_text('{}');(bundle/'programs.json').write_text('{"programs":{}}')
    local=tmp_path/'arena/Local';local.mkdir(parents=True)
    evaluator=local/'vision_eval.lua';evaluator.write_text('old-evaluator')
    old=batch.fingerprint(bundle,1);evaluator.write_text('new-evaluator')
    current=batch.fingerprint(bundle,1);assert current!=old
    bridge=tmp_path/'arena/Capture';bridge.mkdir();(bridge/'FrameServer.java').write_text('new-key-dispatch')
    assert batch.fingerprint(bundle,1)!=current
