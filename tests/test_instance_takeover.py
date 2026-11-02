import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from runtime import InstanceSession
from runtime import control_takeover
from test_named_instances import registry

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def controllers(registry):
    jobs = []

    def start(name, *, dual=False, stubborn=False, child=False):
        ready = registry.project_root / (name + '-ready')
        code = '''
import os,signal,subprocess,sys,time
from pathlib import Path
from contextlib import ExitStack
from runtime import InstanceRegistry,InstanceSession
r=InstanceRegistry(Path(sys.argv[1]))
with ExitStack() as stack:
 stack.enter_context(InstanceSession(sys.argv[2],registry=r).control())
 if sys.argv[3]=='1':stack.enter_context(InstanceSession('main',registry=r).control())
 if sys.argv[4]=='1':signal.signal(signal.SIGTERM,signal.SIG_IGN)
 if sys.argv[5]=='1':
  p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],close_fds=False)
  Path(sys.argv[6]+'-child').write_text(str(p.pid))
 Path(sys.argv[6]).write_text('ready')
 time.sleep(120)
'''
        process = subprocess.Popen([
            sys.executable, '-c', code, str(registry.project_root), name,
            str(int(dual)), str(int(stubborn)), str(int(child)), str(ready),
        ], env={**os.environ, 'PYTHONPATH': str(ROOT / 'agent')}, start_new_session=True)
        jobs.append(process)
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(0.02)
        assert ready.exists()
        return process, ready

    yield start
    for job in jobs:
        try:
            os.killpg(job.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        job.wait(timeout=5)


def test_takeover_stops_only_selected_lock_owner(registry, controllers):
    target, _ = controllers('xiaoli')
    main, _ = controllers('main')
    session = InstanceSession('xiaoli', registry=registry)
    with session.control(takeover=True):
        assert session._owns_control
        assert target.wait(timeout=2) == -signal.SIGTERM
        assert main.poll() is None
    assert not session._owns_control
    with session.control():
        pass


def test_takeover_refuses_controller_that_also_owns_main(registry, controllers):
    target, _ = controllers('xiaoli', dual=True)
    with pytest.raises(RuntimeError, match='其它实例'):
        with InstanceSession('xiaoli', registry=registry).control(takeover=True):
            pytest.fail('不应拿到控制权')
    assert target.poll() is None


def test_takeover_reaps_stubborn_script_and_inherited_lease(registry, controllers):
    target, ready = controllers('xiaoli', stubborn=True, child=True)
    child = int(Path(str(ready) + '-child').read_text())
    with InstanceSession('xiaoli', registry=registry).control(takeover=True, timeout=5):
        assert target.wait(timeout=2) == -signal.SIGKILL
        stat = Path(f'/proc/{child}/stat')
        assert not stat.exists() or stat.read_text().split(') ', 1)[1].startswith('Z')


def test_normal_input_never_stops_an_existing_controller(registry, controllers):
    target, _ = controllers('xiaoli')
    with pytest.raises(RuntimeError, match='已有控制者'):
        with InstanceSession('xiaoli', registry=registry).control():
            pass
    assert target.poll() is None


def test_takeover_without_owner_needs_no_process_signals(registry):
    with InstanceSession('xiaoli', registry=registry).control(takeover=True):
        pass


def test_changed_kernel_owner_is_rechecked_before_signalling(registry, controllers, monkeypatch):
    target, _ = controllers('xiaoli')
    session = InstanceSession('xiaoli', registry=registry)
    key = control_takeover._key((session.spec.work_root / 'control.lock').stat())
    calls = 0

    def changed_locks():
        nonlocal calls
        calls += 1
        return [(target.pid, key)] if calls == 1 else []

    monkeypatch.setattr(control_takeover, '_locks', changed_locks)
    monkeypatch.setattr(control_takeover, '_send', lambda *args: pytest.fail('不能向失去锁身份的 PID 发信号'))
    with pytest.raises(RuntimeError, match='超时'):
        with session.control(takeover=True, timeout=1):
            pass
    assert target.poll() is None


def test_takeover_recovers_orphan_that_inherited_the_lock(registry, controllers):
    target, ready = controllers('xiaoli', child=True)
    main, _ = controllers('main')
    child = int(Path(str(ready) + '-child').read_text())
    target.terminate()
    target.wait(timeout=3)
    session = InstanceSession('xiaoli', registry=registry)
    key = control_takeover._key((session.spec.work_root / 'control.lock').stat())
    # 内核原持锁者可能已经退出，真正阻塞下一次启动的是继承 fd 的子进程。
    assert (child, key) in control_takeover._locks()
    assert (target.pid, key) not in control_takeover._locks()
    with session.control(takeover=True, timeout=5):
        assert session._owns_control
        assert main.poll() is None
    with session.control():
        pass


def test_orphan_inheriting_multiple_instances_is_not_stopped(registry, controllers):
    target, ready = controllers('xiaoli', dual=True, child=True)
    child = int(Path(str(ready) + '-child').read_text())
    target.terminate()
    target.wait(timeout=3)
    with pytest.raises(RuntimeError, match='其它实例'):
        with InstanceSession('xiaoli', registry=registry).control(takeover=True):
            pytest.fail('不应接管同时持有其它实例的残留进程')
    assert Path(f'/proc/{child}').exists()
