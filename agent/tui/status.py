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
    last_event_at: float = 0.0

    def set_node(self, name: str) -> None:
        with self._lock:
            if name:
                self.current_node = name

    def set_current_task(self, *, name: str, entry: str) -> None:
        with self._lock:
            self.current_task_name = name or "—"
            self.current_task_entry = entry or ""

    def set_agent_phase(self, phase: str) -> None:
        with self._lock:
            self.agent_phase = phase

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {
                "task_name": self.current_task_name,
                "task_entry": self.current_task_entry,
                "node": self.current_node,
                "phase": self.agent_phase,
            }


runtime_status = RuntimeStatus()
