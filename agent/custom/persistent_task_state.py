"""Agent 管理的持久化任务启用状态。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from utils.logger import logger
from utils.runtime_paths import get_runtime_paths


_STATE_VERSION = 1
_DAILY_RESET_HOUR = 5


def _local_now() -> datetime:
    return datetime.now().astimezone()


def next_daily_reset(now: datetime) -> datetime:
    candidate = now.replace(
        hour=_DAILY_RESET_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def next_weekly_reset(now: datetime, weekday: int = 0) -> datetime:
    """返回下一个周重置点；weekday=0 表示周一 05:00。"""
    if weekday < 0 or weekday > 6:
        raise ValueError("weekday 必须在 0 到 6 之间")
    candidate = now.replace(
        hour=_DAILY_RESET_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    candidate += timedelta(days=(weekday - candidate.weekday()) % 7)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def _reset_cycle(now: datetime) -> datetime:
    cycle = now.replace(
        hour=_DAILY_RESET_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    if cycle > now:
        cycle -= timedelta(days=1)
    return cycle


@dataclass(frozen=True)
class TaskEnableOverride:
    enabled: bool
    valid_until: datetime | None


class PersistentTaskStateStore:
    def __init__(
        self,
        path: Path,
        *,
        now_factory: Callable[[], datetime] = _local_now,
    ) -> None:
        self.path = Path(path)
        self._now = now_factory
        self._lock = threading.RLock()
        self._states: dict[str, TaskEnableOverride] = {}
        self._node_states: dict[str, dict[str, TaskEnableOverride]] = {}
        self._loaded_cycle: datetime | None = None

    def start(self) -> None:
        """Agent 接管计划时加载一次；后续只在调度安全点按需重载。"""
        self.load()

    def stop(self) -> None:
        """保留给调用方统一清理；当前实现没有后台线程。"""

    def load(self) -> bool:
        now = self._now()
        loaded: dict[str, TaskEnableOverride] = {}
        loaded_nodes: dict[str, dict[str, TaskEnableOverride]] = {}
        removed_expired = False
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or raw.get("version") != _STATE_VERSION:
                    raise ValueError("状态文件版本无效")
                raw_tasks = raw.get("tasks", {})
                if not isinstance(raw_tasks, dict):
                    raise ValueError("tasks 必须是对象")
                for key, value in raw_tasks.items():
                    if not isinstance(key, str) or not key or not isinstance(value, dict):
                        raise ValueError("任务状态格式无效")
                    enabled = value.get("enabled")
                    if not isinstance(enabled, bool):
                        raise ValueError(f"任务 {key!r} 的 enabled 必须是布尔值")
                    raw_until = value.get("valid_until")
                    valid_until = None
                    if raw_until is not None:
                        if not isinstance(raw_until, str):
                            raise ValueError(f"任务 {key!r} 的 valid_until 必须是字符串")
                        valid_until = datetime.fromisoformat(raw_until)
                        if valid_until.tzinfo is None:
                            valid_until = valid_until.replace(tzinfo=now.tzinfo)
                    if valid_until is None or valid_until > now:
                        loaded[key] = TaskEnableOverride(enabled, valid_until)
                    else:
                        removed_expired = True
                raw_nodes = raw.get("nodes", {})
                if not isinstance(raw_nodes, dict):
                    raise ValueError("nodes 必须是对象")
                for entry, raw_entry_nodes in raw_nodes.items():
                    if (
                        not isinstance(entry, str)
                        or not entry
                        or not isinstance(raw_entry_nodes, dict)
                    ):
                        raise ValueError("节点状态的任务 entry 格式无效")
                    entry_nodes: dict[str, TaskEnableOverride] = {}
                    for node, value in raw_entry_nodes.items():
                        if not isinstance(node, str) or not node or not isinstance(value, dict):
                            raise ValueError(f"任务 {entry!r} 的节点状态格式无效")
                        enabled = value.get("enabled")
                        if not isinstance(enabled, bool):
                            raise ValueError(
                                f"节点 {entry!r}/{node!r} 的 enabled 必须是布尔值"
                            )
                        raw_until = value.get("valid_until")
                        valid_until = None
                        if raw_until is not None:
                            if not isinstance(raw_until, str):
                                raise ValueError(
                                    f"节点 {entry!r}/{node!r} 的 valid_until 必须是字符串"
                                )
                            valid_until = datetime.fromisoformat(raw_until)
                            if valid_until.tzinfo is None:
                                valid_until = valid_until.replace(tzinfo=now.tzinfo)
                        if valid_until is None or valid_until > now:
                            entry_nodes[node] = TaskEnableOverride(enabled, valid_until)
                        else:
                            removed_expired = True
                    if entry_nodes:
                        loaded_nodes[entry] = entry_nodes
            except Exception as exc:
                logger.error(f"Agent 任务状态读取失败，保留当前内存状态: {self.path}: {exc}")
                return False

        with self._lock:
            self._states = loaded
            self._node_states = loaded_nodes
            self._loaded_cycle = _reset_cycle(now)
            if removed_expired:
                try:
                    self._write_locked(now)
                except OSError as exc:
                    logger.error(f"Agent 任务过期状态写回失败: {self.path}: {exc}")
        logger.info(
            f"Agent 任务状态已加载: path={str(self.path)!r}, "
            f"tasks={len(loaded)}, nodes={sum(map(len, loaded_nodes.values()))}"
        )
        return True

    def refresh_if_needed(self) -> None:
        now = self._now()
        with self._lock:
            loaded_cycle = self._loaded_cycle
        if loaded_cycle is None or _reset_cycle(now) > loaded_cycle:
            self.load()

    def set(
        self,
        key: str,
        *,
        enabled: bool,
        valid_until: datetime | None,
    ) -> None:
        if not key:
            raise ValueError("任务 key 不能为空")
        now = self._now()
        if valid_until is not None:
            if valid_until.tzinfo is None:
                valid_until = valid_until.replace(tzinfo=now.tzinfo)
            if valid_until <= now:
                raise ValueError("valid_until 必须晚于当前时间")
        with self._lock:
            self._states[key] = TaskEnableOverride(enabled, valid_until)
            self._write_locked(now)

    def is_enabled(self, key: str) -> bool:
        now = self._now()
        with self._lock:
            state = self._states.get(key)
            if state is None:
                return True
            if state.valid_until is not None and state.valid_until <= now:
                self._states.pop(key, None)
                self._write_locked(now)
                return True
            return state.enabled

    def set_node(
        self,
        entry: str,
        node: str,
        *,
        enabled: bool,
        valid_until: datetime | None,
    ) -> None:
        if not entry or not node:
            raise ValueError("任务 entry 和 node 不能为空")
        now = self._now()
        if valid_until is not None:
            if valid_until.tzinfo is None:
                valid_until = valid_until.replace(tzinfo=now.tzinfo)
            if valid_until <= now:
                raise ValueError("valid_until 必须晚于当前时间")
        with self._lock:
            self._node_states.setdefault(entry, {})[node] = TaskEnableOverride(
                enabled, valid_until
            )
            self._write_locked(now)

    def node_overrides(self, entry: str) -> dict[str, bool]:
        now = self._now()
        with self._lock:
            states = self._node_states.get(entry, {})
            expired = [
                node
                for node, state in states.items()
                if state.valid_until is not None and state.valid_until <= now
            ]
            for node in expired:
                states.pop(node, None)
            if not states:
                self._node_states.pop(entry, None)
            if expired:
                self._write_locked(now)
            return {node: state.enabled for node, state in states.items()}

    def seconds_until_state_change(self) -> float:
        """返回下次 05:00 重载或现有状态过期前的秒数。"""
        now = self._now()
        candidates = [next_daily_reset(now)]
        with self._lock:
            candidates.extend(
                state.valid_until
                for state in self._states.values()
                if state.valid_until is not None and state.valid_until > now
            )
            candidates.extend(
                state.valid_until
                for nodes in self._node_states.values()
                for state in nodes.values()
                if state.valid_until is not None and state.valid_until > now
            )
        return max(0.0, (min(candidates) - now).total_seconds())

    def snapshot(self) -> dict[str, TaskEnableOverride]:
        with self._lock:
            return dict(self._states)

    def _write_locked(self, now: datetime) -> None:
        data = {
            "version": _STATE_VERSION,
            "updated_at": now.isoformat(),
            "tasks": {
                key: {
                    "enabled": state.enabled,
                    "valid_until": (
                        state.valid_until.isoformat()
                        if state.valid_until is not None
                        else None
                    ),
                }
                for key, state in sorted(self._states.items())
            },
            "nodes": {
                entry: {
                    node: {
                        "enabled": state.enabled,
                        "valid_until": (
                            state.valid_until.isoformat()
                            if state.valid_until is not None
                            else None
                        ),
                    }
                    for node, state in sorted(nodes.items())
                }
                for entry, nodes in sorted(self._node_states.items())
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

persistent_task_state_store = PersistentTaskStateStore(
    get_runtime_paths().config_dir / "agent_task_state.json"
)
