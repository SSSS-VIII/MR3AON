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
