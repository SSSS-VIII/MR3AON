import json
import os
import sys

import pytest

from runtime.one_shot import run_once


@pytest.mark.parametrize('payload, native_code, expected', [
    ({'status': 'completed', 'exit_code': 0, 'reason': 'done', 'cleanup_complete': True}, 0, 0),
    ({'status': 'completed', 'exit_code': 0, 'reason': 'done', 'cleanup_complete': True}, 9, 1),
    (None, 0, 1),
    ({'status': 'completed', 'exit_code': 0}, 0, 1),
    ({'status': 'completed', 'exit_code': 1}, 0, 1),
    ({'status': 'deferred', 'exit_code': 3, 'reason': 'later', 'cleanup_complete': True}, 0, 3),
])
def test_success_requires_both_native_exit_and_valid_agent_proof(tmp_path, payload, native_code, expected):
    script = tmp_path / 'fake_cli.py'
    script.write_text('import json,os,sys\nfrom pathlib import Path\n'
                      'value=json.loads(sys.argv[1])\n'
                      'if value is not None: Path(os.environ["MR3A_RUN_RESULT"]).write_text(json.dumps(value))\n'
                      'sys.exit(int(sys.argv[2]))\n')
    with (tmp_path / 'control.lock').open('w') as lock:
        result = run_once([sys.executable, str(script), json.dumps(payload), str(native_code)],
                          cwd=tmp_path, env=os.environ.copy(), pass_fds=(lock.fileno(),))
    assert result['exit_code'] == expected


@pytest.mark.parametrize('companion_state', ['stopped', 'failed'])
def test_single_run_waits_for_detached_companion_receipt_after_agent_exit(tmp_path, companion_state):
    import time
    script = tmp_path / 'fake_cli.py'
    script.write_text('''
import json, os, subprocess, sys
from pathlib import Path
receipt = Path(os.environ['MR3A_RUN_CLEANUP_DIR']) / 'companion.json'
receipt.write_text('{"state":"pending"}')
subprocess.Popen([sys.executable, '-c', 'import json,sys,time;from pathlib import Path;time.sleep(1.3);Path(sys.argv[1]).write_text(json.dumps({"state":sys.argv[2],"cleanup_complete":True}))', str(receipt), sys.argv[1]], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path(os.environ['MR3A_RUN_RESULT']).write_text(json.dumps({'status':'completed','exit_code':0,'cleanup_complete':True}))
''')
    started = time.monotonic()
    result = run_once([sys.executable, str(script), companion_state], cwd=tmp_path, env=os.environ.copy(), pass_fds=())
    assert result['exit_code'] == 0
    assert result['companion_cleanup_complete'] is True
    assert result['companion_count'] == 1
    assert time.monotonic() - started >= 1.3


@pytest.mark.parametrize('receipt', [None, {'cleanup_complete': False, 'reason': 'shutdown_failed'}])
def test_missing_or_failed_companion_receipt_blocks_success(tmp_path, monkeypatch, receipt):
    from runtime import one_shot
    monkeypatch.setattr(one_shot, '_COMPANION_CLEANUP_TIMEOUT', 0.15)
    script = tmp_path / 'fake_cli.py'
    script.write_text('''
import json, os, sys
from pathlib import Path
receipt = Path(os.environ['MR3A_RUN_CLEANUP_DIR']) / 'companion.json'
receipt.write_text(sys.argv[1])
Path(os.environ['MR3A_RUN_RESULT']).write_text(json.dumps({'status':'completed','exit_code':0,'cleanup_complete':True}))
''')
    result = run_once([sys.executable, str(script), json.dumps(receipt)],
                      cwd=tmp_path, env=os.environ.copy(), pass_fds=())
    assert result['exit_code'] == 1
    assert result['reason'] == 'companion_cleanup_failed'
    assert result['cleanup_complete'] is False


def test_no_companion_ticket_does_not_spend_cleanup_grace(tmp_path, monkeypatch):
    from runtime import one_shot
    monkeypatch.setattr(one_shot.time, 'sleep', lambda _: pytest.fail('no tickets must return immediately'))
    assert one_shot._await_companion_cleanup(tmp_path) == (True, {})


def test_nested_single_run_gets_its_own_receipts_directory(tmp_path):
    parent_receipts = tmp_path / 'parent-receipts'
    parent_receipts.mkdir()
    (parent_receipts / 'pending.json').write_text('{"state":"pending"}')
    script = tmp_path / 'fake_cli.py'
    script.write_text('''
import json, os, sys
from pathlib import Path
assert os.environ['MR3A_RUN_CLEANUP_DIR'] != sys.argv[1]
Path(os.environ['MR3A_RUN_RESULT']).write_text(json.dumps({'status':'completed','exit_code':0,'cleanup_complete':True}))
''')
    result = run_once([sys.executable, str(script), str(parent_receipts)], cwd=tmp_path,
                      env=dict(os.environ, MR3A_RUN_CLEANUP_DIR=str(parent_receipts)), pass_fds=())
    assert result['exit_code'] == 0
    assert 'companion_count' not in result


def test_sigterm_keeps_interrupted_result_but_waits_for_companion_cleanup(tmp_path):
    import subprocess
    import time
    from pathlib import Path
    script = tmp_path / 'fake_cli.py'
    marker = tmp_path / 'running'
    script.write_text('''
import json, os, signal, subprocess, sys, time
from pathlib import Path
receipt=Path(os.environ['MR3A_RUN_CLEANUP_DIR'])/'companion.json'
receipt.write_text('{"state":"pending"}')
def stop(signum,frame):
    subprocess.Popen([sys.executable,'-c','import sys,time;from pathlib import Path;time.sleep(1.3);Path(sys.argv[1]).write_text(sys.argv[2])',str(receipt),json.dumps({'cleanup_complete':True})],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    Path(os.environ['MR3A_RUN_RESULT']).write_text(json.dumps({'status':'interrupted','exit_code':130,'cleanup_complete':True}))
    sys.exit(0)
signal.signal(signal.SIGUSR1,stop)
Path(sys.argv[1]).touch()
while True: time.sleep(.05)
''')
    runner = '''import json,os,sys
from runtime.one_shot import run_once
result=run_once([sys.executable,sys.argv[1],sys.argv[2]],cwd=sys.argv[3],env=os.environ.copy(),pass_fds=())
print(json.dumps(result),flush=True)
sys.exit(result['exit_code'])
'''
    process = subprocess.Popen([sys.executable, '-c', runner, str(script), str(marker), str(tmp_path)],
                               env=dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / 'agent')),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            assert process.poll() is None
            time.sleep(.02)
        assert marker.exists()
        started = time.monotonic()
        process.terminate()
        output, errors = process.communicate(timeout=8)
        assert process.returncode == 143, errors
        result = json.loads(output)
        assert result['status'] == 'interrupted'
        assert result['companion_cleanup_complete'] is True
        assert time.monotonic() - started >= 1.3
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
