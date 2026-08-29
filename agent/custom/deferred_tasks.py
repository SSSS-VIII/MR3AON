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
from datetime import datetime
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
    base_pipeline_override: Any | None = None
    not_before: datetime | None = None


class ManagedTaskQueue:
    """MaaPiCli bootstrap 交给 Agent 的普通任务队列。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: deque[ManagedTask] = deque()
        self._active = False
        self._current_task_id: int | None = None
        self._current_task: ManagedTask | None = None
        self._task_templates: dict[str, ManagedTask] = {}
        self._disabled_entries: set[str] = set()
        self._recurring_current: dict[int, datetime] = {}

    def activate(
        self,
        tasks: Iterable[ManagedTask],
        bootstrap_task_id: int,
        *,
        disabled_entries: Iterable[str] = (),
    ) -> None:
        task_list = list(tasks)
        with self._lock:
            self._pending = deque(task_list)
            self._active = True
            self._current_task_id = bootstrap_task_id
            self._current_task = None
            self._disabled_entries = set(disabled_entries)
            self._recurring_current = {}
            # MaaPiCli 只提交一次完整计划，Agent 后续插入/重跑任务时
            # 必须能按目标 entry 找回它自己的 PI option override。
            self._task_templates = {}
            for task in task_list:
                self._task_templates.setdefault(task.entry, deepcopy(task))

    def active_for(self, task_id: int) -> bool:
        with self._lock:
            return self._active and self._current_task_id == task_id

    def pop_pending(self) -> ManagedTask | None:
        now = datetime.now().astimezone()
        with self._lock:
            for _ in range(len(self._pending)):
                task = self._pending.popleft()
                if (
                    task.entry not in self._disabled_entries
                    and (task.not_before is None or task.not_before <= now)
                ):
                    return task
                self._pending.append(task)
            return None

    def pending_entries(self) -> set[str]:
        with self._lock:
            return {task.entry for task in self._pending}

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def has_runnable_pending(self) -> bool:
        now = datetime.now().astimezone()
        with self._lock:
            return any(
                task.entry not in self._disabled_entries
                and (task.not_before is None or task.not_before <= now)
                for task in self._pending
            )

    def seconds_until_runnable(self) -> float | None:
        """返回候选自身休眠结束前的秒数；entry 禁用由状态存储处理。"""
        now = datetime.now().astimezone()
        with self._lock:
            due_times = [
                task.not_before
                for task in self._pending
                if task.entry not in self._disabled_entries
                and task.not_before is not None
                and task.not_before > now
            ]
        if not due_times:
            return None
        return max(0.0, (min(due_times) - now).total_seconds())

    def set_disabled_entries(self, entries: Iterable[str]) -> None:
        with self._lock:
            self._disabled_entries = set(entries)

    def transform_candidates(
        self,
        transform: Callable[[ManagedTask], ManagedTask],
    ) -> None:
        """重建尚未执行的候选及其模板，保留每个实例各自的基础配置。"""
        with self._lock:
            self._pending = deque(transform(task) for task in self._pending)
            self._task_templates = {
                entry: transform(task)
                for entry, task in self._task_templates.items()
            }

    def prepend_pending(self, task: ManagedTask) -> None:
        with self._lock:
            self._pending.appendleft(task)

    def set_current(self, task_id: int, task: ManagedTask | None) -> None:
        with self._lock:
            self._current_task_id = task_id
            self._current_task = task

    def retain_current_until(self, task_id: int, valid_until: datetime) -> bool:
        """登记当前实例下一周期的恢复时间；同一实例取最早到期状态。"""
        with self._lock:
            if (
                not self._active
                or self._current_task_id != task_id
                or self._current_task is None
            ):
                return False
            previous = self._recurring_current.get(task_id)
            if previous is None or valid_until < previous:
                self._recurring_current[task_id] = valid_until
            return True

    def release_recurring_current(self, task_id: int) -> ManagedTask | None:
        """任务安全结束时，将已登记实例放回休眠候选队列。"""
        with self._lock:
            valid_until = self._recurring_current.pop(task_id, None)
            if (
                valid_until is None
                or not self._active
                or self._current_task_id != task_id
                or self._current_task is None
            ):
                return None
            current = self._current_task
            retained = ManagedTask(
                name=current.name,
                entry=current.entry,
                pipeline_override=deepcopy(current.pipeline_override),
                base_pipeline_override=deepcopy(current.base_pipeline_override),
                not_before=valid_until,
            )
            self._pending.append(retained)
            return retained

    def current(self) -> ManagedTask | None:
        with self._lock:
            return self._current_task

    def requeue_current(self, task_id: int) -> ManagedTask | None:
        """将当前业务任务放回队首，为到期任务让出调度权。"""
        with self._lock:
            if (
                not self._active
                or self._current_task_id != task_id
                or self._current_task is None
            ):
                return None
            task = self._current_task
            self._pending.appendleft(task)
            # 立即清空可防止同一节点意外重入时重复入队。
            self._current_task = None
            return task

    def pipeline_override_for_entry(self, entry: str) -> dict[str, Any]:
        """返回目标任务的 PI option override。

        自己延后自己时使用当前实例，这样即使同一 entry 在计划中
        出现多次且配置不同，也不会丢失本次配置。
        """
        with self._lock:
            if self._current_task is not None and self._current_task.entry == entry:
                source = (
                    self._current_task.base_pipeline_override
                    if self._current_task.base_pipeline_override is not None
                    else self._current_task.pipeline_override
                )
                return deepcopy(source)
            template = self._task_templates.get(entry)
            if template is None:
                return {}
            source = (
                template.base_pipeline_override
                if template.base_pipeline_override is not None
                else template.pipeline_override
            )
            return deepcopy(source)

    def finish(self) -> None:
        with self._lock:
            self._pending.clear()
            self._active = False
            self._current_task_id = None
            self._current_task = None
            self._task_templates = {}
            self._disabled_entries = set()
            self._recurring_current = {}

    def snapshot(self) -> tuple[bool, list[ManagedTask], int | None]:
        with self._lock:
            return self._active, list(self._pending), self._current_task_id


deferred_task_store = DeferredTaskStore()
managed_task_queue = ManagedTaskQueue()


@dataclass
class _ManagedTaskYieldSignal:
    task_id: int
    generation: int
    ready: bool = False
    timer: threading.Timer | None = None


class ManagedTaskYieldSignalStore:
    """Agent 向当前业务 task 发出的一次性安全让出信号。"""

    def __init__(
        self,
        *,
        timer_factory: Callable[..., threading.Timer] = threading.Timer,
    ) -> None:
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._state: _ManagedTaskYieldSignal | None = None
        self._next_generation = 1

    def arm(self, task_id: int, delay_seconds: float) -> None:
        if task_id <= 0:
            raise ValueError("task_id 必须为正数")
        if delay_seconds < 0:
            raise ValueError("delay_seconds 不能为负数")

        with self._lock:
            self._clear_locked()
            generation = self._next_generation
            self._next_generation += 1
            state = _ManagedTaskYieldSignal(
                task_id=task_id,
                generation=generation,
            )
            timer = self._timer_factory(
                delay_seconds,
                self._mark_ready,
                args=(task_id, generation),
            )
            timer.daemon = True
            state.timer = timer
            self._state = state
            timer.start()

    def _mark_ready(self, task_id: int, generation: int) -> None:
        with self._lock:
            state = self._state
            if (
                state is None
                or state.task_id != task_id
                or state.generation != generation
            ):
                return
            state.ready = True
            state.timer = None

    def consume(self, task_id: int) -> bool:
        """仅由安全退出节点调用；同一个信号最多返回一次 True。"""
        with self._lock:
            state = self._state
            if state is None or state.task_id != task_id or not state.ready:
                return False
            self._state = None
            return True

    def clear(self) -> None:
        with self._lock:
            self._clear_locked()

    def _clear_locked(self) -> None:
        if self._state is not None and self._state.timer is not None:
            self._state.timer.cancel()
        self._state = None


managed_task_yield_signal_store = ManagedTaskYieldSignalStore()


def effective_task_entry(fallback: str) -> str:
    """返回 Agent 当前顶层包装 task 对应的真实业务入口。"""
    current = managed_task_queue.current()
    return current.entry if current is not None else fallback


def pipeline_override_for_entry(entry: str) -> dict[str, Any]:
    """返回本轮 MaaPiCli 计划中目标任务的完整选项覆盖。"""
    return managed_task_queue.pipeline_override_for_entry(entry)
