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


_JUMPBACK_PREFIX = "[JumpBack]"


def bare_node_name(name: str) -> str:
    """去掉 [JumpBack] 前缀，得到可比较的节点名。"""
    text = (name or "").strip()
    if text.startswith(_JUMPBACK_PREFIX):
        return text[len(_JUMPBACK_PREFIX) :].strip()
    return text


@dataclass
class RuntimeStatus:
    """线程安全的 Agent 运行时状态（TUI / sink / 业务共用）。"""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    current_task_name: str = "—"
    current_task_entry: str = ""
    current_node: str = "—"
    # 最近一次识别成功的节点（全局，可供截图覆盖等复用）
    last_recognition_succeeded: str = ""
    # 当前正在轮询的 next 列表（Starting 时写入，结束时清空）
    next_list_parent: str = ""
    _next_list_candidates: frozenset[str] = field(default_factory=frozenset)
    agent_phase: str = "idle"
    waiting_hint: str = ""
    last_event_at: float = 0.0
    exit_requested: bool = False
    exit_reason: str = ""

    def set_node(self, name: str) -> None:
        with self._lock:
            if name:
                self.current_node = name

    def note_recognition_succeeded(self, name: str) -> str:
        """记录识别成功；返回规范化节点名。"""
        bare = bare_node_name(name)
        with self._lock:
            if bare:
                self.last_recognition_succeeded = bare
                self.current_node = bare
        return bare

    def note_next_list_starting(
        self, parent: str, candidates: list[str] | tuple[str, ...]
    ) -> None:
        """next 列表开始轮询。"""
        parent_bare = bare_node_name(parent)
        cands = frozenset(
            bare_node_name(c) for c in candidates if bare_node_name(c)
        )
        with self._lock:
            if parent_bare:
                self.current_node = parent_bare
                self.next_list_parent = parent_bare
            self._next_list_candidates = cands

    def note_next_list_finished(self) -> None:
        with self._lock:
            self.next_list_parent = ""
            self._next_list_candidates = frozenset()

    def next_list_candidates(self) -> frozenset[str]:
        with self._lock:
            return self._next_list_candidates

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
                "last_recognition": self.last_recognition_succeeded,
                "next_list_parent": self.next_list_parent,
                "phase": self.agent_phase,
                "waiting_hint": self.waiting_hint,
                "exit_requested": "1" if self.exit_requested else "",
                "exit_reason": self.exit_reason,
            }


runtime_status = RuntimeStatus()
