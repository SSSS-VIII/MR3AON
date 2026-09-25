from __future__ import annotations

from custom.deferred_tasks import ManagedTask, deferred_task_store, managed_task_queue
from tui.snapshot import build_task_rows, build_waiting_hint
from tui.status import runtime_status


def _reset() -> None:
    managed_task_queue.finish()
    deferred_task_store.clear()
    runtime_status.set_current_task(name="—", entry="")
    runtime_status.set_node("—")
    runtime_status.set_agent_phase("idle")


def test_build_task_rows_marks_running_pending_deferred():
    _reset()
    tasks = [
        ManagedTask("启动游戏", "启动游戏entry", {}),
        ManagedTask("通灵巡逻", "通灵巡逻entry", {}),
        ManagedTask("小屋修炼", "小屋修炼entry", {}),
        ManagedTask("领取饭团", "领取饭团entry", {}),
    ]
    managed_task_queue.activate(tasks, bootstrap_task_id=1)

    # 重建 pending：去掉当前任务与延后任务
    kept: list[ManagedTask] = []
    while managed_task_queue.has_pending():
        task = managed_task_queue.pop_pending()
        assert task is not None
        if task.entry not in {"通灵巡逻entry", "小屋修炼entry"}:
            kept.append(task)
    for task in reversed(kept):
        managed_task_queue.prepend_pending(task)

    managed_task_queue.set_current(
        1, ManagedTask("通灵巡逻", "通灵巡逻entry", {})
    )
    deferred_task_store.arm(
        key="小屋修炼",
        entry="小屋修炼entry",
        delay_seconds=7200,
        pipeline_override={},
    )

    rows = {row.entry: row for row in build_task_rows()}
    assert rows["通灵巡逻entry"].phase == "running"
    assert rows["小屋修炼entry"].phase == "deferred"
    assert rows["启动游戏entry"].phase == "pending"
    assert rows["领取饭团entry"].phase == "pending"

    _reset()


def test_build_waiting_hint_shows_nearest_deferred_name():
    _reset()
    tasks = [
        ManagedTask("通灵巡逻", "通灵巡逻entry", {}),
        ManagedTask("小屋修炼", "小屋修炼entry", {}),
    ]
    managed_task_queue.activate(tasks, bootstrap_task_id=1)
    deferred_task_store.arm(
        key="小屋修炼",
        entry="小屋修炼entry",
        delay_seconds=7200,
        pipeline_override={},
    )
    deferred_task_store.arm(
        key="通灵巡逻",
        entry="通灵巡逻entry",
        delay_seconds=60,
        pipeline_override={},
    )

    hint = build_waiting_hint()
    assert hint.startswith("通灵巡逻")
    assert "m" in hint or "s" in hint

    _reset()
