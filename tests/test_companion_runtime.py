import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from runtime import companion
from runtime.instances import InstanceSession, write_json
from test_named_instances import registry

ROOT = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


def test_request_is_private_short_lived_and_uses_instance_and_live_nickname(tmp_path, monkeypatch):
    monkeypatch.setenv("MR3A_COMPANION_DIR", str(tmp_path))
    write_json(tmp_path / "session.json", {"name": "small", "task_id": 42})
    assert companion.read_session() == {"name": "small", "task_id": 42}
    assert companion.publish_state("ready", nickname="小号现场昵称")
    state = companion._read(tmp_path / "state.json")
    assert state["state"] == "ready"
    assert state["nickname"] == "小号现场昵称"
    write_json(tmp_path / "request.json", {"token": "round1", "expires_at": time.monotonic() + 5,
                                           "leader_name": "大号"})
    assert companion.read_request()["leader_name"] == "大号"
    write_json(tmp_path / "request.json", {"token": "round1", "expires_at": time.monotonic() - 1})
    assert companion.read_request() is None
    monkeypatch.delenv("MR3A_COMPANION_DIR")
    assert companion.read_session() == {}
    assert companion.read_request() is None
    assert not companion.publish_state("ready")


@pytest.mark.parametrize("name,reason", [
    ("main", "相同"), ("../main", "实例名"),
    ("", "实例名"), ("small", "启动游戏配置"),
])
def test_invalid_companion_never_launches_worker(registry, name, reason):
    manager = companion.CompanionManager(registry=registry)
    with patch.object(companion.subprocess, "Popen", side_effect=AssertionError("must not start")):
        assert not manager.start(name, 1)
    assert reason in manager.status()["reason"]


def test_background_worker_does_not_inherit_parent_lock_and_stop_revokes_ready(registry, monkeypatch, tmp_path):
    spec = registry.get("small")
    registry.prepare(spec)
    config = json.loads(spec.config_path.read_text())
    config["task"] = [{"name": "启动游戏", "option": [{"name": "password", "inputs": {"secret": "small-only"}}]}]
    write_json(spec.config_path, config)
    before = spec.config_path.read_bytes()
    manager = companion.CompanionManager(registry=registry)
    popen = subprocess.Popen
    captured = {}

    def fake_worker(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        directory, fd = command[4], int(command[5])
        code = '''
import json,os,sys
from pathlib import Path
directory=Path(sys.argv[1]);fd=int(sys.argv[2])
assert not any("parent-control-marker" in os.readlink(p) for p in Path('/proc/self/fd').iterdir() if p.exists())
(directory/'state.json').write_text(json.dumps({'state':'ready'}))
os.read(fd,1)
(directory/'worker.json').write_text(json.dumps({'state':'stopped','cleanup_complete':True}))
receipt=json.loads((directory/'session.json').read_text()).get('cleanup_receipt')
if receipt: Path(receipt).write_text(json.dumps({'cleanup_complete':True}))
'''
        return popen([sys.executable, "-c", code, directory, str(fd)], **kwargs)

    with (tmp_path / "parent-control-marker").open("w") as parent_lock:
        os.set_inheritable(parent_lock.fileno(), True)
        monkeypatch.setenv("MR3A_COMPANION_DIR", "/parent/private")
        monkeypatch.setenv("MR3A_RUN_ONCE", "1")
        monkeypatch.setenv("MR3A_RUN_CLEANUP_DIR", str(tmp_path / "receipts"))
        with patch.object(companion.subprocess, "Popen", side_effect=fake_worker):
            assert manager.start("small", 42)
        assert manager.wait_ready(3)
        env = captured["kwargs"]["env"]
        assert env["MR3A_INSTANCE_NAME"] == "small"
        assert env["MR3A_SHOW_WINDOW"] == env["MR3A_TUI"] == "0"
        assert "MR3A_COMPANION_DIR" not in env
        assert "MR3A_RUN_CLEANUP_DIR" not in env
        assert "MR3A_RUN_ONCE" not in env
        assert parent_lock.fileno() not in captured["kwargs"]["pass_fds"]
        session = companion._read(manager._current.directory / "session.json")
        assert session['name'] == 'small' and session['task_id'] == 42
        assert 'game_id' not in session
        token = manager.permit_invitation(10, leader_name="大号")
        assert token
        request = companion._read(manager._current.directory / "request.json")
        assert request["token"] == token and request["leader_name"] == "大号"
        assert manager.stop(task_id=100)
        assert manager.status()["state"] == "ready"
        assert manager.stop(task_id=42)
        assert not manager.wait_ready()
        assert manager.shutdown(3)
    wait_for(lambda: manager._current.final is not None)
    assert manager.status() == {"state": "stopped", "cleanup_complete": True}
    assert spec.config_path.read_bytes() == before
    assert json.loads(next((tmp_path / "receipts").glob("*.json")).read_text())["cleanup_complete"] is True


WORKER_FIXTURE = '''
from contextlib import contextmanager
import fcntl,json,os,sys,time
from pathlib import Path
from types import SimpleNamespace
from runtime.companion_worker import run_worker
root=Path(sys.argv[1]); mode=sys.argv[2];fd=int(sys.argv[3])
class Session:
    def __init__(self,name):
        self.spec=SimpleNamespace(config_path=root/'config.json',work_root=root)
        self.owned=False
    @contextmanager
    def control(self):
        if mode=='busy': raise RuntimeError('instance busy')
        with (root/'control.lock').open('w') as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.owned=True
            marker=root/'leases'
            marker.write_text(str(int(marker.read_text())+1 if marker.exists() else 1))
            try: yield f.fileno()
            finally: self.owned=False
    def shutdown(self,timeout=None):
        assert self.owned
        with (root/'control.lock').open('w') as other:
            try: fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: pass
            else: raise AssertionError('shutdown after lease released')
        if mode=='parent_retry_cleanup':
            (root/'cleanup-enter').touch()
            time.sleep(0.5)
        (root/'shutdown').write_text('done')
        if mode in ('shutdown_failure','retry_shutdown_failure'): raise RuntimeError('backend failure')
@contextmanager
def prepare(session,**kwargs):
    assert kwargs['tasks']==['启动游戏','每日悬赏小号']
    assert kwargs['task_options']['启动游戏']['启动时屏蔽组队邀请']=='否'
    marker=root/'prepares'
    marker.write_text(str(int(marker.read_text())+1 if marker.exists() else 1))
    if mode=='startup_failure': raise RuntimeError('boot failed')
    if mode=='cancel_startup':
        (root/'preparing').touch()
        time.sleep(60)
    yield SimpleNamespace(command=[sys.executable,str(root/'cli.py'),mode],env=os.environ.copy(),pass_fds=())
sys.exit(run_worker('small',root/'state',fd,float(sys.argv[4]),float(sys.argv[5]),session_factory=Session,prepare=prepare))
'''

CLI_FIXTURE = '''
import json,os,signal,sys,time
from pathlib import Path
mode=sys.argv[1]; directory=Path(os.environ['MR3A_COMPANION_DIR'])
attempt=int((directory.parent/'prepares').read_text())
if mode not in ('never_ready','retry_shutdown_failure','parent_retry_cleanup') and not (mode=='retry_ready' and attempt==1):
    (directory/'state.json').write_text(json.dumps({'state':'ready'}))
def finish(signum=None,frame=None):
    Path(os.environ['MR3A_RUN_RESULT']).write_text(json.dumps({'status':'completed','exit_code':0,'cleanup_complete':True}))
    sys.exit(0)
signal.signal(signal.SIGUSR1,finish)
if mode in ('waiting','never_ready','lifetime','retry_shutdown_failure','parent_retry_cleanup') or (mode=='retry_ready' and attempt==1):
    while True: time.sleep(0.05)
if mode=='failed': sys.exit(8)
finish()
'''


@pytest.fixture
def worker(tmp_path):
    (tmp_path / "state").mkdir()
    write_json(tmp_path / "state/session.json", {"cleanup_receipt": str(tmp_path / "receipt.json")})
    write_json(tmp_path / "config.json", {"task": [{"name": "启动游戏"}]})
    script = tmp_path / "worker.py"
    script.write_text(WORKER_FIXTURE)
    (tmp_path / "cli.py").write_text(CLI_FIXTURE)
    processes = []
    fds = []

    def start(mode, startup=10, lifetime=30):
        read_fd, write_fd = os.pipe()
        process = subprocess.Popen([sys.executable, str(script), str(tmp_path), mode,
                                    str(read_fd), str(startup), str(lifetime)],
                                   env={**os.environ, "PYTHONPATH": str(ROOT / "agent")},
                                   pass_fds=(read_fd,), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        os.close(read_fd)
        fds.append(write_fd)
        processes.append(process)
        return process, write_fd

    yield start
    for fd in fds:
        try: os.close(fd)
        except OSError: pass
    for process in processes:
        try: process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)


@pytest.mark.parametrize("mode,code,reason,shutdown", [
    ("completed", 0, "task_finished", True),
    ("failed", 1, "cli_failed", True),
    ("startup_failure", 1, "boot failed", True),
    ("busy", 1, "instance busy", False),
    ("shutdown_failure", 1, "shutdown_failed", True),
])
def test_worker_cleans_owned_environment_on_every_exit(worker, tmp_path, mode, code, reason, shutdown):
    process, _ = worker(mode)
    output, errors = process.communicate(timeout=8)
    assert process.returncode == code, (output, errors)
    status = companion._read(tmp_path / "state/worker.json")
    assert status["reason"] == reason
    assert (tmp_path / "shutdown").exists() == shutdown
    assert json.loads((tmp_path / "receipt.json").read_text()) == status
    with (tmp_path / "control.lock").open("w") as free:
        fcntl.flock(free, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("mode,marker", [("waiting", "state/state.json"), ("cancel_startup", "preparing")])
def test_parent_pipe_eof_reclaims_running_or_partially_started_environment(worker, tmp_path, mode, marker):
    process, fd = worker(mode)
    wait_for(lambda: (tmp_path / marker).exists())
    os.close(fd)
    output, errors = process.communicate(timeout=8)
    assert process.returncode == 0, (output, errors)
    status = companion._read(tmp_path / "state/worker.json")
    assert status == {"state": "stopped", "reason": "parent_finished", "cleanup_complete": True}
    assert (tmp_path / "shutdown").exists()


@pytest.mark.parametrize("mode,startup,lifetime,reason", [
    ("never_ready", 0.5, 10, "startup_timeout"),
    ("lifetime", 5, 0.5, "lifetime_timeout"),
])
def test_unready_or_stuck_companion_has_bounded_lifetime(worker, tmp_path, mode, startup, lifetime, reason):
    process, _ = worker(mode, startup, lifetime)
    output, errors = process.communicate(timeout=8)
    assert process.returncode == 1, (output, errors)
    assert companion._read(tmp_path / "state/worker.json")["reason"] == reason
    assert (tmp_path / "shutdown").exists()


def test_shutdown_under_existing_lease_does_not_reacquire(registry):
    session = InstanceSession("small", registry=registry)
    with session.control(), patch.object(session, "_backend") as backend:
        session.shutdown(timeout=3)
        assert session._owns_control
    backend.assert_called_once_with("stop", timeout=3)


def test_reaper_thread_start_failure_cancels_real_worker_and_keeps_cleanup_evidence(registry, monkeypatch, tmp_path):
    spec = registry.get('small')
    registry.prepare(spec)
    config = json.loads(spec.config_path.read_text())
    config['task'] = [{'name': '启动游戏'}]
    write_json(spec.config_path, config)
    monkeypatch.setenv('MR3A_RUN_ONCE', '1')
    monkeypatch.setenv('MR3A_RUN_CLEANUP_DIR', str(tmp_path / 'receipts'))
    manager = companion.CompanionManager(registry=registry)
    popen = subprocess.Popen
    processes = []
    observed = tmp_path / 'worker-observed-pending'

    def fake_worker(command, **kwargs):
        code = '''
import fcntl,json,os,sys,time
from pathlib import Path
directory=Path(sys.argv[1]);fd=int(sys.argv[2]);observed=Path(sys.argv[3])
with (directory/'owned.lock').open('w') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # Thread startup failed in the parent, but this real child must see EOF.
    assert os.read(fd,1)==b''
    session=json.loads((directory/'session.json').read_text())
    receipt=Path(session['cleanup_receipt'])
    assert json.loads(receipt.read_text())['state']=='pending'
    observed.touch()
    time.sleep(.1)
result={'state':'stopped','cleanup_complete':True,'worker_verified':True}
(directory/'worker.json').write_text(json.dumps(result))
receipt.write_text(json.dumps(result))
'''
        process = popen([sys.executable, '-c', code, command[4], command[5], str(observed)], **kwargs)
        processes.append(process)
        return process

    with patch.object(companion.subprocess, 'Popen', side_effect=fake_worker), \
         patch.object(companion.threading.Thread, 'start', side_effect=RuntimeError('cannot start new thread')) as thread_start:
        assert manager.start('small', 99) is False
    thread_start.assert_called_once()  # No replacement thread is used as a fallback.
    assert observed.is_file()
    assert len(processes) == 1 and processes[0].returncode == 0
    assert manager.status() == {'state': 'failed', 'reason': 'cannot start new thread'}
    receipt = json.loads(next((tmp_path / 'receipts').glob('*.json')).read_text())
    assert receipt == {'state': 'stopped', 'cleanup_complete': True, 'worker_verified': True}
    assert manager._handles[0].parent_fd is None
    assert manager._handles[0].final == receipt
    assert not manager._handles[0].directory.exists()
    assert manager.shutdown(timeout=0)


def test_failed_reaper_keeps_pending_session_if_worker_cleanup_has_not_finished(registry, monkeypatch, tmp_path):
    spec = registry.get('small')
    registry.prepare(spec)
    config = json.loads(spec.config_path.read_text())
    config['task'] = [{'name': '启动游戏'}]
    write_json(spec.config_path, config)
    monkeypatch.setenv('MR3A_RUN_ONCE', '1')
    monkeypatch.setenv('MR3A_RUN_CLEANUP_DIR', str(tmp_path / 'receipts'))
    manager = companion.CompanionManager(registry=registry)
    popen = subprocess.Popen
    allowed = tmp_path / 'allow-cleanup'
    processes = []

    def fake_worker(command, **kwargs):
        code = '''
import json,os,sys,time
from pathlib import Path
directory=Path(sys.argv[1]);fd=int(sys.argv[2]);allowed=Path(sys.argv[3])
assert os.read(fd,1)==b''
while not allowed.exists(): time.sleep(.02)
receipt=Path(json.loads((directory/'session.json').read_text())['cleanup_receipt'])
result={'state':'stopped','cleanup_complete':True}
(directory/'worker.json').write_text(json.dumps(result))
receipt.write_text(json.dumps(result))
'''
        process = popen([sys.executable, '-c', code, command[4], command[5], str(allowed)], **kwargs)
        processes.append(process)
        actual_wait = process.wait
        calls = 0

        def first_wait_times_out(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise subprocess.TimeoutExpired('worker', 45)
            return actual_wait(*args, **kwargs)

        process.wait = first_wait_times_out
        return process

    try:
        with patch.object(companion.subprocess, 'Popen', side_effect=fake_worker), \
             patch.object(companion.threading.Thread, 'start', side_effect=RuntimeError('cannot start new thread')):
            assert manager.start('small', 99) is False
        handle = manager._handles[0]
        assert handle.parent_fd is None
        assert (handle.directory / 'session.json').exists()
        assert handle.final is None
        assert companion._read(handle.receipt)['state'] == 'pending'
        assert 'cleanup_complete' not in companion._read(handle.receipt)
        assert not manager.shutdown(timeout=0)
        allowed.touch()
        assert manager.shutdown(timeout=3)
        assert companion._read(handle.receipt)['cleanup_complete'] is True
    finally:
        allowed.touch()
        for process in processes:
            process.wait(timeout=3)


def test_startup_timeout_retries_once_under_same_lease_and_can_finish(worker, tmp_path):
    process, _ = worker("retry_ready", startup=0.5, lifetime=10)
    output, errors = process.communicate(timeout=8)
    assert process.returncode == 0, (output, errors)
    assert (tmp_path / "prepares").read_text() == "2"
    assert output.count(b"retrying once") == 1
    assert (tmp_path / "leases").read_text() == "1"
    status = companion._read(tmp_path / "receipt.json")
    assert status == {"state": "stopped", "reason": "task_finished", "cleanup_complete": True}


def test_repeated_startup_timeout_exhausts_after_two_attempts(worker, tmp_path):
    process, _ = worker("never_ready", startup=0.5, lifetime=10)
    output, errors = process.communicate(timeout=8)
    assert process.returncode == 1, (output, errors)
    assert (tmp_path / "prepares").read_text() == "2"
    assert output.count(b"retrying once") == 1
    assert companion._read(tmp_path / "receipt.json")["reason"] == "startup_timeout"


def test_parent_cancel_during_retry_still_cleans_and_has_no_early_receipt(worker, tmp_path):
    process, fd = worker("never_ready", startup=0.6, lifetime=10)
    wait_for(lambda: (tmp_path / "prepares").exists() and (tmp_path / "prepares").read_text() == "2")
    assert not (tmp_path / "receipt.json").exists()
    os.close(fd)
    output, errors = process.communicate(timeout=8)
    assert process.returncode == 0, (output, errors)
    assert companion._read(tmp_path / "receipt.json") == {"state": "stopped", "reason": "parent_finished", "cleanup_complete": True}


def test_failed_cleanup_prevents_startup_retry(worker, tmp_path):
    process, _ = worker("retry_shutdown_failure", startup=0.5, lifetime=10)
    output, errors = process.communicate(timeout=8)
    assert process.returncode == 1, (output, errors)
    assert (tmp_path / "prepares").read_text() == "1"
    assert companion._read(tmp_path / "receipt.json")["cleanup_complete"] is False


def test_startup_retry_keeps_original_overall_lifetime(worker, tmp_path):
    process, _ = worker("never_ready", startup=0.4, lifetime=0.8)
    output, errors = process.communicate(timeout=8)
    assert process.returncode == 1, (output, errors)
    assert (tmp_path / "prepares").read_text() == "2"
    assert companion._read(tmp_path / "receipt.json")["reason"] == "lifetime_timeout"


def test_main_ready_budget_includes_both_launches_and_cleanup():
    pipeline = json.loads((ROOT / "assets/resource/pipeline/每日悬赏.json").read_text())
    budget = pipeline["每日悬赏设置小号等待时限"]["action"]["param"]["custom_action_param"]["duration_ms"]
    assert budget >= 2 * (companion.CompanionManager().startup_timeout + 30) * 1000


def test_parent_cancel_during_first_cleanup_prevents_retry(worker, tmp_path):
    process, fd = worker("parent_retry_cleanup", startup=0.5, lifetime=10)
    wait_for(lambda: (tmp_path / "cleanup-enter").exists())
    assert not (tmp_path / "receipt.json").exists()
    os.close(fd)
    output, errors = process.communicate(timeout=8)
    assert process.returncode == 0, (output, errors)
    assert (tmp_path / "prepares").read_text() == "1"
    assert companion._read(tmp_path / "receipt.json")["reason"] == "parent_finished"
