"""Agent 运行时 TUI 共享状态（供 sink / 调度与 Textual 读写）。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

TaskPhase = Literal["running", "pending", "deferred", "done", "disabled"]


@dataclass(frozen=True)
class TaskRow:
    entry: str
    name: str
    phase: TaskPhase
    detail: str = ""


@dataclass
class RuntimeStatus:
    """线程安全的当前节点/任务展示状态。"""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    current_task_name: str = "—"
    current_task_entry: str = ""
    current_node: str = "—"
    agent_phase: str = "idle"
    waiting_hint: str = ""
    last_event_at: float = 0.0
    exit_requested: bool = False
    exit_reason: str = ""

    def set_node(self, name: str) -> None:
        with self._lock:
            if name:
                self.current_node = name

    def set_current_task(self, *, name: str, entry: str) -> None:
        with self._lock:
            self.current_task_name = name or "—"
            self.current_task_entry = entry or ""

    def set_agent_phase(self, phase: str, *, waiting_hint: str | None = None) -> None:
        with self._lock:
            self.agent_phase = phase
            if waiting_hint is not None:
                self.waiting_hint = waiting_hint
            elif phase != "waiting":
                self.waiting_hint = ""

    def set_waiting_hint(self, hint: str) -> None:
        with self._lock:
            self.waiting_hint = hint

    def request_exit(self, reason: str = "") -> None:
        """请 TUI 自行 exit，恢复终端后再杀 PiCli。"""
        with self._lock:
            self.exit_requested = True
            self.exit_reason = reason or self.exit_reason
            self.agent_phase = "done"
            self.waiting_hint = ""

    def should_exit(self) -> bool:
        with self._lock:
            return self.exit_requested

    def clear_exit_request(self) -> None:
        with self._lock:
            self.exit_requested = False
            self.exit_reason = ""

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {
                "task_name": self.current_task_name,
                "task_entry": self.current_task_entry,
                "node": self.current_node,
                "phase": self.agent_phase,
                "waiting_hint": self.waiting_hint,
                "exit_requested": "1" if self.exit_requested else "",
                "exit_reason": self.exit_reason,
            }


runtime_status = RuntimeStatus()
