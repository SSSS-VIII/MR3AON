"""Supervise the shared CLI for one invocation, including signals and cleanup."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

_COMPANION_CLEANUP_TIMEOUT = 45

_EXEC_CLI = """import os, sys
os.environ['MR3A_PICLI_PID'] = str(os.getpid())
os.execv(sys.argv[1], sys.argv[1:])
"""


def _group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _signal_group(pid, signum):
    try:
        os.killpg(pid, signum)
    except ProcessLookupError:
        pass


def _await_companion_cleanup(directory):
    """Wait only for registered workers; their receipts outlive the Agent.

    The native CLI grants its Agent only eight seconds after disconnect. Device
    cleanup belongs to the independent worker, so this wait must happen outside
    that Agent and outside the ten-second CLI signal grace period.
    """
    tickets = list(directory.glob("*.json"))
    if not tickets:
        return True, {}
    deadline = time.monotonic() + _COMPANION_CLEANUP_TIMEOUT
    while True:
        results = []
        for path in tickets:
            try:
                value = json.loads(path.read_text())
                results.append(value if isinstance(value, dict) else {})
            except (OSError, ValueError):
                results.append({})
        pending = any(type(value.get("cleanup_complete")) is not bool for value in results)
        if not pending or time.monotonic() >= deadline:
            ok = all(value.get("cleanup_complete") is True for value in results)
            details = {"companion_cleanup_complete": ok, "companion_count": len(tickets)}
            if not ok:
                details["companion_cleanup_errors"] = [
                    value.get("reason", "cleanup_timeout") for value in results
                    if value.get("cleanup_complete") is not True
                ]
            return ok, details
        time.sleep(0.05)


def run_once(command, *, cwd, env, pass_fds):
    interrupted = None
    stop_deadline = None
    process = None

    def stop(signum, frame):
        nonlocal interrupted, stop_deadline
        del frame
        interrupted = signum
        stop_deadline = time.monotonic() + 10
        if process is not None and process.poll() is None:
            try:
                os.kill(process.pid, signal.SIGUSR1)
            except ProcessLookupError:
                pass

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with tempfile.TemporaryDirectory(prefix='mr3a-run-result-') as directory:
            result_path = Path(directory) / 'result.json'
            cleanup_dir = Path(directory) / 'companions'
            cleanup_dir.mkdir(mode=0o700)
            child_env = dict(env, MR3A_RUN_ONCE='1', MR3A_RUN_RESULT=str(result_path),
                             MR3A_RUN_CLEANUP_DIR=str(cleanup_dir))
            process = subprocess.Popen(
                [sys.executable, '-c', _EXEC_CLI, *command], cwd=cwd, env=child_env,
                pass_fds=pass_fds, start_new_session=True,
            )
            try:
                while process.poll() is None:
                    if stop_deadline is not None and time.monotonic() >= stop_deadline:
                        _signal_group(process.pid, signal.SIGKILL)
                    time.sleep(0.05)
                returncode = process.wait()
            finally:
                # A failed CLI can leave its Agent holding the inherited lease.
                # Keep the supervising lease until this invocation's group exits.
                deadline = time.monotonic() + 1
                while _group_alive(process.pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                leaked = _group_alive(process.pid)
                if leaked:
                    _signal_group(process.pid, signal.SIGTERM)
                    time.sleep(0.2)
                    if _group_alive(process.pid):
                        _signal_group(process.pid, signal.SIGKILL)
                if process.poll() is None:
                    process.wait(timeout=5)
            companion_ok, companion_detail = _await_companion_cleanup(cleanup_dir)
            if interrupted is not None:
                return {'status': 'interrupted', 'exit_code': 128 + interrupted,
                        'reason': signal.Signals(interrupted).name, **companion_detail}
            if not companion_ok:
                return {'status': 'failed', 'exit_code': 1, 'reason': 'companion_cleanup_failed',
                        'cleanup_complete': False, **companion_detail}
            if returncode != 0 or leaked:
                return {'status': 'failed', 'exit_code': 1, 'reason': 'cli_failed' if returncode else 'child_cleanup_failed',
                        'cli_exit_code': returncode, **companion_detail}
            try:
                result = json.loads(result_path.read_text())
                if result['status'] not in {'completed', 'skipped', 'failed', 'deferred', 'yielded', 'interrupted'}:
                    raise ValueError('unknown status')
                from runtime.run_result import STATUS_CODES
                if result.get('cleanup_complete') is not True:
                    raise ValueError('agent cleanup incomplete')
                if result['exit_code'] != STATUS_CODES[result['status']]:
                    raise ValueError('invalid exit code')
                return {**result, **companion_detail}
            except (OSError, ValueError, KeyError, TypeError):
                return {'status': 'failed', 'exit_code': 1, 'reason': 'missing_or_invalid_agent_result', **companion_detail}
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
