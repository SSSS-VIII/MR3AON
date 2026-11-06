"""The real run entry must return control to a shell that sources it."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('invocation', ['. run', 'source ./run', './run'])
@pytest.mark.parametrize('arguments, expected', [('--help', 0), ('--invalid-shell-test-option', 2)])
def test_run_returns_to_parent_without_changing_shell_state(invocation, arguments, expected):
    script = '''
set -u
ROOT=caller-root
export PYTHONPATH=caller-python-path
before=$-
%s %s > /dev/null 2>&1
status=$?
printf 'PARENT_ALIVE status=%%s flags=%%s root=%%s path=%%s\n' "$status" "$([[ "$-" == "$before" ]] && echo same)" "$ROOT" "$PYTHONPATH"
''' % (invocation, arguments)
    result = subprocess.run(['bash', '--noprofile', '--norc', '-c', script], cwd=ROOT,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f'PARENT_ALIVE status={expected} flags=same root=caller-root path=caller-python-path'


def test_sourcing_does_not_export_previously_unset_variables():
    env = {key: value for key, value in os.environ.items() if key not in {'ROOT', 'PYTHONPATH'}}
    script = '. ./run --help >/dev/null; printf "PARENT_ALIVE root=%s path=%s\\n" "${ROOT-unset}" "${PYTHONPATH-unset}"'
    result = subprocess.run(['bash', '--noprofile', '--norc', '-c', script], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'PARENT_ALIVE root=unset path=unset'
