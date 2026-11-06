"""Invocation result shared by Agent callbacks and the supervising launcher."""

import json
import os
from pathlib import Path
import threading

STATUS_CODES = {"completed": 0, "skipped": 0, "failed": 1, "deferred": 3, "yielded": 4, "interrupted": 130}
_PRIORITY = {"completed": 0, "skipped": 1, "yielded": 2, "deferred": 3, "interrupted": 4, "failed": 5}


def single_run() -> bool:
    return os.environ.get("MR3A_RUN_ONCE") == "1"


class InvocationResult:
    def __init__(self):
        self._lock = threading.Lock()
        self._result = None

    def record(self, status: str, reason: str) -> None:
        if not single_run():
            return
        with self._lock:
            if self._result is not None and _PRIORITY[self._result['status']] >= _PRIORITY[status]:
                return
            self._result = {"status": status, "exit_code": STATUS_CODES[status], "reason": reason}
            self._write_result()

    def _write_result(self):
        path = Path(os.environ["MR3A_RUN_RESULT"])
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self._result, ensure_ascii=False))
        temporary.replace(path)

    def finalize(self):
        if not single_run():
            return
        with self._lock:
            if self._result is not None:
                self._result['cleanup_complete'] = True
                self._write_result()

    def on_exit(self, reason: str) -> None:
        if reason == "queue_finished":
            self.record("completed", reason)
        elif reason == "agent_disconnected":
            # A disconnect following queue_finished is normal. An early one
            # supplies no completion proof, so the launcher treats it as failure.
            return
        elif reason in {"user_quit", "wait_interrupted", "tasker_stopping"}:
            self.record("interrupted", reason)
        elif reason:
            self.record("failed", reason)


invocation_result = InvocationResult()
