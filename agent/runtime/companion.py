"""One task's companion instance, supervised independently of Maa callbacks.

The worker owns the companion lease. A private pipe ties its lifetime to the
parent Agent, including parent crashes, without inheriting the parent's lease.
"""

from __future__ import annotations

import atexit
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import uuid

from runtime.instances import InstanceRegistry, write_json

READY_STATES = {"ready", "teamed", "fighting"}
TERMINAL_STATES = {"failed", "stopped"}


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _has_startup(config_path: Path) -> bool:
    tasks = _read(config_path).get("task")
    return isinstance(tasks, list) and any(
        isinstance(task, dict) and task.get("name") == "启动游戏" for task in tasks)


def _directory() -> Path | None:
    value = os.environ.get("MR3A_COMPANION_DIR")
    return Path(value) if value else None


def read_session() -> dict:
    """Return this invocation's named-instance and lifecycle metadata."""
    directory = _directory()
    return _read(directory / "session.json") if directory else {}


def publish_state(state: str, **details) -> bool:
    directory = _directory()
    if directory is None or not directory.is_dir():
        return False
    write_json(directory / "state.json", {**details, "state": state,
                                          "updated_at": time.monotonic()})
    return True


def read_request() -> dict | None:
    """Only a current, short-lived invitation permit authorizes acceptance."""
    directory = _directory()
    request = _read(directory / "request.json") if directory else {}
    expiry = request.get("expires_at")
    if (not request.get("token") or not isinstance(expiry, (int, float))
            or not math.isfinite(expiry) or expiry <= time.monotonic()):
        return None
    return request


def _status(directory: Path) -> dict:
    worker = _read(directory / "worker.json")
    if worker.get("state") in TERMINAL_STATES | {"stopping"}:
        return worker
    return {**worker, **_read(directory / "state.json")}


@dataclass
class _Handle:
    process: subprocess.Popen
    directory: Path
    parent_fd: int | None
    task_id: int
    name: str
    receipt: Path | None = None
    stopping: bool = False
    final: dict | None = None


class CompanionManager:
    def __init__(self, *, registry=None, startup_timeout=150, lifetime=1800):
        self.registry = registry or InstanceRegistry()
        self.startup_timeout = startup_timeout
        self.lifetime = lifetime
        self._lock = threading.RLock()
        self._current: _Handle | None = None
        self._handles: list[_Handle] = []
        self._last = {"state": "stopped", "reason": "not_started"}

    def start(self, name: str, task_id: int) -> bool:
        """Start without waiting for Android; invalid/busy environments fall back."""
        with self._lock:
            if self._current is not None and self._current.process.poll() is None:
                if self._current.task_id == task_id and not self._current.stopping:
                    return self.status().get("state") not in TERMINAL_STATES | {"stopping"}
                self.stop()
            directory = None
            receipt = None
            process = handle = None
            read_fd = write_fd = None
            try:
                name = unicodedata.normalize("NFC", name.strip())
                if name == os.environ.get("MR3A_INSTANCE_NAME", "main"):
                    raise ValueError("小号实例不能与当前实例相同")
                spec = self.registry.get(name)
                if not _has_startup(spec.config_path):
                    raise ValueError("小号实例尚未保存自己的启动游戏配置")
                parent = spec.work_root / "data/companions"
                parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                directory = Path(tempfile.mkdtemp(prefix="daily-bounty-", dir=parent))
                receipts = os.environ.get("MR3A_RUN_CLEANUP_DIR")
                if receipts and os.environ.get("MR3A_RUN_ONCE") == "1":
                    receipt = Path(receipts) / f"{uuid.uuid4().hex}.json"
                    write_json(receipt, {"state": "pending", "name": spec.name})
                write_json(directory / "session.json", {
                    "name": spec.name, "task_id": task_id,
                    "parent_instance": os.environ.get("MR3A_INSTANCE_NAME", "main"),
                    "cleanup_receipt": str(receipt) if receipt else None,
                })
                write_json(directory / "worker.json", {"state": "starting"})
                read_fd, write_fd = os.pipe()
                debug = spec.work_root / "debug"
                debug.mkdir(mode=0o700, parents=True, exist_ok=True)
                log_path = debug / f"companion-{directory.name}.log"
                env = spec.environment()
                env.update(MR3A_TUI="0", MR3A_SHOW_WINDOW="0",
                           PYTHONPATH=str(spec.project_root / "agent"))
                with log_path.open("w") as output:
                    process = subprocess.Popen([
                        sys.executable, "-m", "runtime.companion_worker", spec.name,
                        str(directory), str(read_fd), str(self.startup_timeout), str(self.lifetime),
                    ], cwd=spec.project_root, env=env, stdin=subprocess.DEVNULL,
                        stdout=output, stderr=subprocess.STDOUT, pass_fds=(read_fd,),
                        start_new_session=True)
                os.close(read_fd)
                read_fd = None
                handle = _Handle(process, directory, write_fd, task_id, spec.name, receipt)
                write_fd = None
                self._current = handle
                self._handles.append(handle)
                threading.Thread(target=self._reap, args=(handle,), daemon=True,
                                 name=f"companion-reap-{spec.name}").start()
                return True
            except (OSError, ValueError, RuntimeError, TypeError) as exc:
                self._last = {"state": "failed", "reason": str(exc)}
                self._current = None
                if process is not None:
                    # Popen transferred responsibility to a real worker. In
                    # particular, Thread.start() can fail after that transfer.
                    # Close its parent pipe, retain its session/receipt, and
                    # synchronously reap this exceptional path without another
                    # thread. Only the worker may attest to device cleanup.
                    if handle is None:
                        handle = _Handle(process, directory, write_fd, task_id, spec.name, receipt)
                        write_fd = None
                        self._handles.append(handle)
                    handle.stopping = True
                    if handle.parent_fd is not None:
                        os.close(handle.parent_fd)
                        handle.parent_fd = None
                    try:
                        process.wait(timeout=45)
                    except subprocess.TimeoutExpired:
                        # Keep the handle and pending evidence for shutdown();
                        # the worker still owns cleanup and its time limits.
                        pass
                    else:
                        self._reap(handle)
                    return False
                if receipt is not None:
                    # No worker owns an environment when spawning fails.
                    write_json(receipt, {"state": "failed", "reason": "not_started", "cleanup_complete": True})
                if directory is not None:
                    shutil.rmtree(directory, ignore_errors=True)
                return False
            finally:
                for fd in (read_fd, write_fd):
                    if fd is not None:
                        os.close(fd)

    def _reap(self, handle):
        code = handle.process.wait()
        result = _status(handle.directory)
        if result.get("state") not in TERMINAL_STATES:
            result = {"state": "failed", "reason": "worker_exited", "exit_code": code}
        if handle.receipt is not None and "cleanup_complete" not in _read(handle.receipt):
            write_json(handle.receipt, {"state": "failed", "reason": "worker_exited_without_cleanup", "cleanup_complete": False})
        with self._lock:
            handle.final = result
            if handle.parent_fd is not None:
                os.close(handle.parent_fd)
                handle.parent_fd = None
        shutil.rmtree(handle.directory, ignore_errors=True)

    def status(self) -> dict:
        with self._lock:
            handle = self._current
            if handle is None:
                return dict(self._last)
            if handle.final is not None:
                return dict(handle.final)
            if handle.stopping:
                return {"state": "stopping", "reason": "parent_finished"}
            status = _status(handle.directory)
            if handle.process.poll() is not None and status.get("state") not in TERMINAL_STATES:
                return {"state": "failed", "reason": "worker_exited"}
            return status

    def wait_ready(self, timeout=0, cancelled=None, states=None) -> bool:
        expected = READY_STATES if states is None else states
        deadline = time.monotonic() + max(0, timeout)
        while True:
            if cancelled is not None and cancelled():
                self.stop()
                return False
            state = self.status().get("state")
            if state in expected:
                return True
            if state in TERMINAL_STATES | {"stopping"} or time.monotonic() >= deadline:
                return False
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))

    def permit_invitation(self, seconds=20, **details) -> str | None:
        with self._lock:
            handle = self._current
            if handle is None or self.status().get("state") != "ready":
                return None
            token = uuid.uuid4().hex
            write_json(handle.directory / "request.json", {
                **details, "token": token, "expires_at": time.monotonic() + min(60, max(1, seconds)),
            })
            return token

    def revoke_invitation(self) -> None:
        with self._lock:
            handle = self._current
            if handle is not None and handle.directory.is_dir():
                write_json(handle.directory / "request.json", {})

    def stop(self, task_id=None, *, wait=False, timeout=15) -> bool:
        with self._lock:
            handle = self._current
            if handle is None or (task_id is not None and task_id != handle.task_id):
                return True
            handle.stopping = True
            try:
                self.revoke_invitation()
            finally:
                # Even an unwritable state directory must not prevent cleanup.
                if handle.parent_fd is not None:
                    os.close(handle.parent_fd)
                    handle.parent_fd = None
        if wait:
            try:
                handle.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return False
        return handle.process.poll() is not None if wait else True

    def shutdown(self, timeout=15) -> bool:
        """Signal immediately, then allow a bounded wait at Agent shutdown."""
        self.stop()
        deadline = time.monotonic() + timeout
        with self._lock:
            handles = tuple(self._handles)
        for handle in handles:
            try:
                handle.process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                return False
        # Exiting the worker is insufficient if its backend cleanup failed.
        with self._lock:
            return all((handle.final or _status(handle.directory)).get("cleanup_complete") is True
                       for handle in handles)


companion_manager = CompanionManager()
atexit.register(companion_manager.stop)
