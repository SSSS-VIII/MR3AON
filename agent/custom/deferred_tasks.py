"""Agent 侧延后任务状态表。

定时线程只更新 Python 内存，不调用 Maa API。bootstrap 自定义动作在每个
子任务返回后检查这份状态，并在自身结束前运行下一项。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class DeferredTask:
    key: str
    entry: str
    due_at: float
    pipeline_override: dict[str, Any]


@dataclass
class _DeferredTaskState:
    task: DeferredTask
    generation: int
    ready: bool = False
    timer: threading.Timer | None = None


class DeferredTaskStore:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        timer_factory: Callable[..., threading.Timer] = threading.Timer,
    ) -> None:
        self._clock = clock
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._states: dict[str, _DeferredTaskState] = {}
        self._next_generation = 1

    def arm(
        self,
        *,
        key: str,
        entry: str,
        delay_seconds: float,
        pipeline_override: dict[str, Any] | None = None,
    ) -> DeferredTask:
        if not key or not entry:
            raise ValueError("key 和 entry 不能为空")
        if delay_seconds < 0:
            raise ValueError("delay_seconds 不能为负数")

        with self._lock:
            old = self._states.get(key)
            if old and old.timer:
                old.timer.cancel()

            generation = self._next_generation
            self._next_generation += 1
            task = DeferredTask(
                key=key,
                entry=entry,
                due_at=self._clock() + delay_seconds,
                pipeline_override=deepcopy(pipeline_override or {}),
            )
            state = _DeferredTaskState(task=task, generation=generation)
            timer = self._timer_factory(
                delay_seconds,
                self._mark_ready,
                args=(key, generation),
            )
            timer.daemon = True
            state.timer = timer
            self._states[key] = state
            timer.start()
            return task

    def _mark_ready(self, key: str, generation: int) -> None:
        with self._lock:
            state = self._states.get(key)
            if state is None or state.generation != generation:
                return
            state.ready = True
            state.timer = None

    def _refresh_due_locked(self) -> None:
        now = self._clock()
        for state in self._states.values():
            if not state.ready and state.task.due_at <= now:
                state.ready = True
                if state.timer:
                    state.timer.cancel()
                    state.timer = None

    def claim_ready(self, *, excluding_entry: str | None = None) -> list[DeferredTask]:
        """取走所有到期项，按到期时间排序。失败时可通过 release_ready 放回。"""
        with self._lock:
            self._refresh_due_locked()
            ready = [
                state.task
                for state in self._states.values()
                if state.ready and state.task.entry != excluding_entry
            ]
            ready.sort(key=lambda task: (task.due_at, task.key))
            for task in ready:
                self._states.pop(task.key, None)
            return ready

    def consume_ready_for_entry(self, entry: str) -> list[DeferredTask]:
        """同一入口本来就要执行时，视为已满足，避免再前置一份。"""
        with self._lock:
            self._refresh_due_locked()
            matched = [
                state.task
                for state in self._states.values()
                if state.ready and state.task.entry == entry
            ]
            for task in matched:
                self._states.pop(task.key, None)
            return matched

    def release_ready(self, tasks: list[DeferredTask]) -> None:
        with self._lock:
            for task in tasks:
                if task.key in self._states:
                    continue
                generation = self._next_generation
                self._next_generation += 1
                self._states[task.key] = _DeferredTaskState(
                    task=task,
                    generation=generation,
                    ready=True,
                )

    def clear(self) -> None:
        with self._lock:
            for state in self._states.values():
                if state.timer:
                    state.timer.cancel()
            self._states.clear()

    def snapshot(self) -> list[tuple[DeferredTask, bool]]:
        with self._lock:
            self._refresh_due_locked()
            return [(state.task, state.ready) for state in self._states.values()]

    def seconds_until_next(self) -> float | None:
        with self._lock:
            self._refresh_due_locked()
            if not self._states:
                return None
            if any(state.ready for state in self._states.values()):
                return 0.0
            return max(
                0.0,
                min(state.task.due_at for state in self._states.values())
                - self._clock(),
            )


@dataclass(frozen=True)
class ManagedTask:
    name: str
    entry: str
    pipeline_override: Any


class ManagedTaskQueue:
    """MaaPiCli bootstrap 交给 Agent 的普通任务队列。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: deque[ManagedTask] = deque()
        self._active = False
        self._current_task_id: int | None = None
        self._current_task: ManagedTask | None = None
        self._task_templates: dict[str, ManagedTask] = {}

    def activate(self, tasks: Iterable[ManagedTask], bootstrap_task_id: int) -> None:
        task_list = list(tasks)
        with self._lock:
            self._pending = deque(task_list)
            self._active = True
            self._current_task_id = bootstrap_task_id
            self._current_task = None
            # MaaPiCli 只提交一次完整计划，Agent 后续插入/重跑任务时
            # 必须能按目标 entry 找回它自己的 PI option override。
            self._task_templates = {}
            for task in task_list:
                self._task_templates.setdefault(task.entry, deepcopy(task))

    def active_for(self, task_id: int) -> bool:
        with self._lock:
            return self._active and self._current_task_id == task_id

    def pop_pending(self) -> ManagedTask | None:
        with self._lock:
            return self._pending.popleft() if self._pending else None

    def prepend_pending(self, task: ManagedTask) -> None:
        with self._lock:
            self._pending.appendleft(task)

    def set_current(self, task_id: int, task: ManagedTask | None) -> None:
        with self._lock:
            self._current_task_id = task_id
            self._current_task = task

    def current(self) -> ManagedTask | None:
        with self._lock:
            return self._current_task

    def pipeline_override_for_entry(self, entry: str) -> dict[str, Any]:
        """返回目标任务的 PI option override。

        自己延后自己时使用当前实例，这样即使同一 entry 在计划中
        出现多次且配置不同，也不会丢失本次配置。
        """
        with self._lock:
            if self._current_task is not None and self._current_task.entry == entry:
                return deepcopy(self._current_task.pipeline_override)
            template = self._task_templates.get(entry)
            return deepcopy(template.pipeline_override) if template is not None else {}

    def finish(self) -> None:
        with self._lock:
            self._pending.clear()
            self._active = False
            self._current_task_id = None
            self._current_task = None
            self._task_templates = {}

    def snapshot(self) -> tuple[bool, list[ManagedTask], int | None]:
        with self._lock:
            return self._active, list(self._pending), self._current_task_id


deferred_task_store = DeferredTaskStore()
managed_task_queue = ManagedTaskQueue()


def effective_task_entry(fallback: str) -> str:
    """返回 Agent 当前顶层包装 task 对应的真实业务入口。"""
    current = managed_task_queue.current()
    return current.entry if current is not None else fallback


def pipeline_override_for_entry(entry: str) -> dict[str, Any]:
    """返回本轮 MaaPiCli 计划中目标任务的完整选项覆盖。"""
    return managed_task_queue.pipeline_override_for_entry(entry)
