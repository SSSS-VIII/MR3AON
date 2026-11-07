"""Own one companion's control lease from cold startup through full shutdown."""

from __future__ import annotations

import os
from pathlib import Path
import select
import signal
import sys
import threading
import time

from runtime.companion import READY_STATES, _has_startup, _read
from runtime.instances import InstanceSession, write_json
from runtime.launcher import prepare_command
from runtime.one_shot import run_once


class _Cancelled(Exception):
    pass


def run_worker(name, directory, parent_fd, startup_timeout=150, lifetime=1800,
               *, session_factory=InstanceSession, prepare=prepare_command, run=run_once):
    directory = Path(directory)
    receipt_value = _read(directory / "session.json").get("cleanup_receipt")
    receipt = Path(receipt_value) if receipt_value else None
    os.set_inheritable(parent_fd, False)
    lifetime_started = time.monotonic()
    finished = threading.Event()
    cancelled = threading.Event()
    cancellation_reason = []
    started = lifetime_started
    ready = False
    attempt = 0

    def parent_gone():
        return bool(select.select([parent_fd], [], [], 0)[0] and not os.read(parent_fd, 1))

    def record(state, **details):
        try:
            write_json(directory / "worker.json", {**details, "state": state,
                       **({"attempt": attempt + 1} if state in {"running", "retrying"} else {})})
        except OSError as exc:
            print(f"companion status write failed: {exc}", file=sys.stderr, flush=True)

    def interrupt(signum, frame):
        del signum, frame
        raise _Cancelled("companion_cancelled")

    def watch_parent():
        nonlocal ready
        while not finished.wait(0.1):
            state = _read(directory / "state.json")
            ready = ready or state.get("state") in READY_STATES
            reason = None
            if parent_gone():
                reason = "parent_finished"
            elif state.get("state") == "failed":
                reason = state.get("reason", "companion_task_failed")
            elif time.monotonic() - lifetime_started >= lifetime:
                reason = "lifetime_timeout"
            elif not ready and time.monotonic() - started >= startup_timeout:
                reason = "startup_timeout"
            if reason:
                cancellation_reason.append(reason)
                cancelled.set()
                try:
                    retrying = reason == "startup_timeout" and attempt == 0
                    record("retrying" if retrying else "stopping", reason=reason)
                finally:
                    os.kill(os.getpid(), signal.SIGTERM)
                return

    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGINT, signal.SIGTERM)}
    monitor = None
    result = {"state": "failed", "reason": "startup_failed"}
    try:
        session = session_factory(name)
        if not _has_startup(session.spec.config_path):
            raise ValueError("小号实例尚未保存自己的启动游戏配置")
        # Keep the same lease over the failed launch, shutdown, and retry.
        with session.control() as control_fd:
            for attempt in range(2):
                finished = threading.Event()
                cancelled = threading.Event()
                cancellation_reason = []
                started = time.monotonic()
                ready = False
                if parent_gone():
                    result = {"state": "stopped", "reason": "parent_finished", "cleanup_complete": True}
                    break
                for sig in previous:
                    signal.signal(sig, interrupt)
                monitor = threading.Thread(target=watch_parent, name="companion-parent-watch", daemon=True)
                monitor.start()
                try:
                    with prepare(session, tasks=["启动游戏", "每日悬赏小号"],
                                 task_options={"启动游戏": {"启动时屏蔽组队邀请": "否"}},
                                 once=True, ready_timeout=startup_timeout) as prepared:
                        prepared.env.update(MR3A_COMPANION_DIR=str(directory),
                                            MR3A_SHOW_WINDOW="0", MR3A_TUI="0")
                        if cancelled.is_set():
                            raise _Cancelled("companion_cancelled")
                        record("running")
                        outcome = run(prepared.command, cwd=session.spec.work_root,
                                      env=prepared.env, pass_fds=(control_fd, *prepared.pass_fds))
                        result = {"state": "stopped" if outcome.get("exit_code") == 0 else "failed",
                                  "reason": "task_finished" if outcome.get("exit_code") == 0 else outcome.get("reason", "task_failed")}
                except _Cancelled:
                    result = {"state": "stopped", "reason": "parent_finished"}
                except Exception as exc:
                    result = {"state": "failed", "reason": str(exc)}
                finally:
                    finished.set()
                    for sig in previous:
                        signal.signal(sig, signal.SIG_IGN)
                    monitor.join(timeout=1)
                    if cancellation_reason:
                        reason = cancellation_reason[0]
                        result = {"state": "stopped" if reason == "parent_finished" else "failed", "reason": reason}
                    retry = result["reason"] == "startup_timeout" and attempt == 0
                    record("retrying" if retry else "stopping", reason=result["reason"])
                    try:
                        session.shutdown(timeout=30)
                        result["cleanup_complete"] = True
                    except Exception as exc:
                        result = {"state": "failed", "reason": "shutdown_failed",
                                  "error": str(exc), "cleanup_complete": False}
                        retry = False
                if not retry:
                    break
                if parent_gone():
                    result.update(state="stopped", reason="parent_finished")
                    break
                if time.monotonic() - lifetime_started >= lifetime:
                    result.update(state="failed", reason="lifetime_timeout")
                    break
                # A timed-out child cannot leave a stale status or permission in
                # the next CLI invocation. No receipt is emitted until final release.
                for filename in ("state.json", "request.json"):
                    (directory / filename).unlink(missing_ok=True)
                record("retrying", reason="startup_timeout")
                print("companion startup timed out; retrying once after owned shutdown", flush=True)

    except _Cancelled:
        reason = cancellation_reason[0] if cancellation_reason else "parent_finished"
        result = {"state": "stopped" if reason == "parent_finished" else "failed",
                  "reason": reason, "cleanup_complete": True}
    except Exception as exc:
        # In particular, an occupied lease never grants authority to shut it down.
        result = {"state": "failed", "reason": str(exc), "cleanup_complete": True}
    finally:
        finished.set()
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        if monitor is not None:
            monitor.join(timeout=1)
        os.close(parent_fd)
        record(**result)
        if receipt is not None:
            # Written after releasing control(), even if the parent Agent has
            # already exited. The one-shot launcher independently awaits this.
            write_json(receipt, result)
        print(result, flush=True)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0 if result["state"] == "stopped" else 1


if __name__ == "__main__":
    sys.exit(run_worker(sys.argv[1], sys.argv[2], int(sys.argv[3]),
                        float(sys.argv[4]), float(sys.argv[5])))
