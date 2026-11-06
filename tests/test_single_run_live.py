"""Opt-in native CLI/Agent smoke through the launcher, without game input."""

import json
import fcntl
import pty
import select
import struct
import termios
import os
from pathlib import Path
import signal
import subprocess
import time

import pytest

from runtime import InstanceSession
from custom.persistent_task_state import PersistentTaskStateStore
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not os.environ.get('MR3A_ONCE_LIVE'), reason='需指定已就绪且空闲的实例，只运行无点击夹具')

_LAUNCH = '''
from dataclasses import replace
import os, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from runtime import InstanceSession
from runtime import launcher
name, work = sys.argv[1:3]
real = InstanceSession(name)
spec = replace(real.spec, work_root=Path(work))
env = real.spec.environment(real._address())
env['MR3A_WORK_ROOT'] = work
session = SimpleNamespace(spec=spec, control=real.control, ensure_ready=real.ensure_ready,
                          bind_config=lambda: None, environment=lambda: env)
registry = SimpleNamespace(prepare=lambda spec: None)
sys.argv = ['run', name, '--no-window', '--once', '--task', 'Smoke',
            '--task-options', '{"Smoke":{"enabled":true}}']
with patch.object(launcher, 'InstanceRegistry', return_value=registry), patch.object(launcher, 'InstanceSession', return_value=session):
    sys.exit(launcher.main())
'''


def owned_processes(work):
    marker = f'MR3A_WORK_ROOT={work}'.encode()
    found = []
    for path in Path('/proc').iterdir():
        if path.name.isdigit():
            try:
                if marker in (path / 'environ').read_bytes().split(b'\0'):
                    found.append(int(path.name))
            except OSError:
                pass
    return found


@pytest.mark.parametrize('mode, code', [('completed', 0), ('already', 0), ('failed', 1), ('deferred', 3), ('yielded', 4), ('interrupt', 130), ('terminate', 143), ('tui_completed', 0), ('tui_quit', 130)])
def test_native_once_completion_failure_and_lease_release(tmp_path, mode, code):
    session = InstanceSession(os.environ['MR3A_ONCE_LIVE'])
    serial = session._address()
    before_real = session.spec.config_path.read_bytes()
    work = tmp_path / mode
    (work / 'resource/pipeline').mkdir(parents=True)
    (work / 'config').mkdir()
    entry = '每周逆袭悬赏entry'
    pipeline = {entry: {'next': ['Selected', 'Fail']},
                'Selected': {'enabled': False, 'action': {'type': 'Custom', 'param': {
                    'custom_action': 'SetManagedTaskPersistentState', 'custom_action_param': {
                        'enabled': False, 'valid_until': 'next_daily_reset'}}}, 'next': ['Stop']},
                'Stop': {'action': 'StopTask'},
                'Fail': {'recognition': {'type': 'Custom', 'param': {'custom_recognition': 'TimeBefore', 'custom_recognition_param': {'time': '00:00'}}}, 'timeout': 200, 'on_error': []}}
    if mode in {'interrupt', 'terminate', 'tui_quit'}:
        pipeline[entry] = {'post_delay': 15000, 'next': ['Stop']}
    elif mode == 'failed':
        pipeline[entry] = {'action': {'type': 'Custom', 'param': {'custom_action': 'SetManagedTaskPersistentState', 'custom_action_param': {'enabled': 'invalid'}}}, 'on_error': []}
    elif mode in {'deferred', 'yielded'}:
        action = 'ScheduleDeferredTask' if mode == 'deferred' else 'ManagedTaskSchedulerYieldCurrent'
        param = {'key': 'later', 'entry': entry, 'daily_times': ['20:00']} if mode == 'deferred' else {}
        pipeline[entry] = {'action': {'type': 'Custom', 'param': {'custom_action': action, 'custom_action_param': param}}, 'next': ['Stop']}
    (work / 'resource/pipeline/smoke.json').write_text(json.dumps(pipeline))
    interface = {'interface_version': 2, 'name': 'OnceSmoke', 'version': 'test',
                 'controller': [{'name': 'ADB', 'type': 'Adb'}],
                 'resource': [{'name': 'smoke', 'path': ['./resource']}],
                 'task': [{'name': 'Smoke', 'entry': entry, 'option': ['enabled']}],
                 'option': {'enabled': {'type': 'switch', 'default_case': 'No', 'cases': [
                     {'name': 'Yes', 'pipeline_override': {'Selected': {'enabled': True}}},
                     {'name': 'No', 'pipeline_override': {'Selected': {'enabled': False}}}]}},
                 'agent': {'child_exec': str(ROOT / '.venv/bin/python'), 'child_args': ['-u', str(ROOT / 'agent/main.py')]}}
    (work / 'interface.json').write_text(json.dumps(interface))
    config = {'controller': {'name': 'ADB'}, 'resource': 'smoke', 'adb': {
        'name': serial + '-/usr/bin/adb', 'adb_path': '/usr/bin/adb', 'address': serial},
        'task': [{'name': 'Smoke', 'option': [{'name': 'enabled', 'value': 'No'}]}]}
    config_path = work / 'config/maa_pi_config.json'
    config_path.write_text(json.dumps(config))
    before_fixture = config_path.read_bytes()
    (work / 'config/maa_option.json').write_text('{"logging":true,"stdout_level":0}')
    (work / 'config/pip_config.json').write_text('{"enable_pip_install":false}')
    if mode == 'already':
        state = PersistentTaskStateStore(work / 'config/agent_task_state.json')
        state.set(entry, enabled=False, valid_until=datetime.now().astimezone() + timedelta(days=1))
    use_tui = mode.startswith('tui_')
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'agent'), MR3A_TUI='1' if use_tui else '0', TERM='xterm-256color')
    env.pop('KITTY_WINDOW_ID', None)
    master, slave = pty.openpty()
    before_terminal = termios.tcgetattr(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 90, 0, 0))
    with (work / 'console.log').open('w+') as output:
        process = subprocess.Popen([str(ROOT / '.venv/bin/python'), '-c', _LAUNCH, session.spec.name, str(work)], env=env, stdin=slave if use_tui else subprocess.DEVNULL, stdout=slave if use_tui else output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            if use_tui:
                captured = bytearray()
                sent_quit = False
                deadline = time.monotonic() + 40
                while process.poll() is None and time.monotonic() < deadline:
                    if select.select([master], [], [], .05)[0]:
                        captured.extend(os.read(master, 65536))
                    started = any('Agent 调度已提交' in p.read_text() for p in (work / 'debug/custom').glob('*.log'))
                    if mode == 'tui_quit' and not sent_quit and started and b'\x1b[?1049h' in captured:
                        os.write(master, b'q')
                        sent_quit = True
                while select.select([master], [], [], 0)[0]:
                    captured.extend(os.read(master, 65536))
                output.write(captured.decode(errors='replace'))
                output.flush()
                assert b'\x1b[?1049l' in captured
                assert termios.tcgetattr(slave) == before_terminal
            if mode in {'interrupt', 'terminate'}:
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if any('Agent 调度已提交' in p.read_text() for p in (work / 'debug/custom').glob('*.log')):
                        break
                    assert process.poll() is None, work
                    time.sleep(.1)
                with pytest.raises(RuntimeError, match='已有控制者'):
                    with session.control():
                        pass
                process.send_signal(signal.SIGINT if mode == 'interrupt' else signal.SIGTERM)
            assert process.wait(timeout=40) == code, work
            output.seek(0)
            text = output.read()
            result = json.loads(next(line.removeprefix('MR3A_RESULT ') for line in text.splitlines() if line.startswith('MR3A_RESULT ')))
            assert result['exit_code'] == code
            if mode == 'already':
                assert result['status'] == 'skipped'
            assert 'leaked semaphore' not in text
            assert not owned_processes(work)
            with session.control():
                pass
            assert config_path.read_bytes() == before_fixture
            assert session.spec.config_path.read_bytes() == before_real
            assert session.status()['session'] == 'RUNNING'
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            os.close(master)
            os.close(slave)
