"""从 Agent 队列 / 延后表 / 持久化状态拼出 TUI 任务列表。"""

from __future__ import annotations

import time
from datetime import datetime

from custom.deferred_tasks import deferred_task_store, managed_task_queue
from custom.persistent_task_state import persistent_task_state_store

from .status import TaskRow, runtime_status


def _fmt_eta(seconds: float | None) -> str:
    if seconds is None:
        return ""
    sec = max(0, int(seconds))
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"


def _display_name(entry: str, name: str | None = None) -> str:
    if name:
        return name
    return entry[:-5] if entry.endswith("entry") else entry


def build_task_rows() -> list[TaskRow]:
    """完整列表：计划内任务 + 仅出现在延后表里的项。"""
    now = datetime.now().astimezone()
    mono = time.monotonic()

    current = managed_task_queue.current()
    _active, pending, _task_id = managed_task_queue.snapshot()
    pending_by_entry = {t.entry: t for t in pending}
    deferred_states = deferred_task_store.snapshot()
    deferred_by_entry: dict[str, tuple] = {}
    for task, ready in deferred_states:
        deferred_by_entry[task.entry] = (task, ready)
        # 部分登记用业务名当 key，列表仍按 entry 对齐
        deferred_by_entry.setdefault(task.key, (task, ready))
    persistent = persistent_task_state_store.snapshot()

    plan = managed_task_queue.plan_order()
    # 延后表里可能有计划外 entry，追加到末尾
    extra = [
        task.entry
        for task, _ready in deferred_states
        if task.entry not in plan
    ]
    order = list(plan)
    for entry in extra:
        if entry not in order:
            order.append(entry)

    rows: list[TaskRow] = []
    seen: set[str] = set()

    for entry in order:
        if entry in seen:
            continue
        seen.add(entry)
        template = managed_task_queue.template_for(entry)
        name = _display_name(entry, template.name if template else None)

        if current is not None and current.entry == entry:
            rows.append(TaskRow(entry=entry, name=name, phase="running"))
            continue

        deferred = deferred_by_entry.get(entry)
        if deferred is not None:
            task, ready = deferred
            eta = 0.0 if ready else max(0.0, task.due_at - mono)
            rows.append(
                TaskRow(
                    entry=entry,
                    name=name,
                    phase="deferred",
                    detail=_fmt_eta(eta) if not ready else "ready",
                )
            )
            continue

        pending_task = pending_by_entry.get(entry)
        if pending_task is not None:
            if pending_task.not_before is not None and pending_task.not_before > now:
                eta = (pending_task.not_before - now).total_seconds()
                rows.append(
                    TaskRow(
                        entry=entry,
                        name=name,
                        phase="deferred",
                        detail=_fmt_eta(eta),
                    )
                )
            else:
                rows.append(TaskRow(entry=entry, name=name, phase="pending"))
            continue

        override = persistent.get(entry)
        if override is not None and not override.enabled:
            rows.append(TaskRow(entry=entry, name=name, phase="done"))
            continue

        # 计划里有模板但此刻不在队列（例如尚未 activate）：显示为 pending
        if template is not None:
            rows.append(TaskRow(entry=entry, name=name, phase="pending"))

    # 同步当前任务名到 runtime_status（调度侧也会写，这里兜底）
    if current is not None:
        runtime_status.set_current_task(name=current.name, entry=current.entry)

    return rows


def build_view_model() -> dict:
    status = runtime_status.snapshot()
    return {
        "status": status,
        "tasks": build_task_rows(),
    }
