"""管理任务硬失败后应丢掉当前实例，避免队列卡死、TUI 挂住。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from custom.deferred_tasks import ManagedTask, managed_task_queue
from custom.sink.deferred_tasks import _advance_after_hard_end
from tui.status import runtime_status


def _reset() -> None:
    managed_task_queue.finish()
    runtime_status.clear_exit_request()


def test_abandon_current_drops_recurring_and_clears():
    _reset()
    tasks = [
        ManagedTask("每周逆袭悬赏", "每周逆袭悬赏", {}),
        ManagedTask("竞技场", "竞技场", {}),
    ]
    managed_task_queue.activate(tasks, bootstrap_task_id=10)
    current = managed_task_queue.pop_pending()
    assert current is not None
    managed_task_queue.set_current(42, current)
    until = datetime.now(timezone.utc) + timedelta(hours=1)
    assert managed_task_queue.retain_current_until(42, until)
    assert managed_task_queue.active_for(42)

    abandoned = managed_task_queue.abandon_current(42)
    assert abandoned is not None
    assert abandoned.entry == "每周逆袭悬赏"
    assert not managed_task_queue.active_for(42)
    assert managed_task_queue.current() is None
    # 硬失败不把实例塞回休眠队列
    pending = managed_task_queue.pending_entries()
    assert "每周逆袭悬赏" not in pending
    assert "竞技场" in pending
    _reset()


def test_abandon_current_ignores_stale_task_id():
    _reset()
    managed_task_queue.activate(
        [ManagedTask("竞技场", "竞技场", {})],
        bootstrap_task_id=1,
    )
    task = managed_task_queue.pop_pending()
    managed_task_queue.set_current(7, task)
    assert managed_task_queue.abandon_current(99) is None
    assert managed_task_queue.active_for(7)
    _reset()


def test_advance_after_hard_end_dispatches_when_still_current():
    _reset()
    managed_task_queue.activate(
        [
            ManagedTask("每周逆袭悬赏", "每周逆袭悬赏", {}),
            ManagedTask("竞技场", "竞技场", {}),
        ],
        bootstrap_task_id=1,
    )
    current = managed_task_queue.pop_pending()
    managed_task_queue.set_current(5, current)
    tasker = MagicMock()

    with (
        patch(
            "custom.sink.deferred_tasks.dispatch_next",
            return_value=True,
        ) as dispatch,
        patch("custom.sink.deferred_tasks.time.sleep"),
    ):
        _advance_after_hard_end(tasker, 5, "每周逆袭悬赏", outcome="Failed")

    dispatch.assert_called_once_with(tasker)
    assert managed_task_queue.current() is None
    assert not runtime_status.should_exit()
    _reset()


def test_advance_after_hard_end_noop_after_stop_task_path():
    """StopTask 已切到下一项时，Succeeded 不应再 abandon/dispatch。"""
    _reset()
    managed_task_queue.activate(
        [ManagedTask("竞技场", "竞技场", {})],
        bootstrap_task_id=1,
    )
    nxt = managed_task_queue.pop_pending()
    managed_task_queue.set_current(99, nxt)  # 已是新 task_id
    tasker = MagicMock()

    with (
        patch(
            "custom.sink.deferred_tasks.dispatch_next",
            return_value=True,
        ) as dispatch,
        patch("custom.sink.deferred_tasks.time.sleep"),
    ):
        _advance_after_hard_end(tasker, 5, "每周逆袭悬赏", outcome="Succeeded")

    dispatch.assert_not_called()
    assert managed_task_queue.active_for(99)
    _reset()


def test_advance_after_hard_end_exits_tui_when_dispatch_fails():
    _reset()
    managed_task_queue.activate(
        [ManagedTask("每周逆袭悬赏", "每周逆袭悬赏", {})],
        bootstrap_task_id=1,
    )
    current = managed_task_queue.pop_pending()
    managed_task_queue.set_current(3, current)
    tasker = MagicMock()

    with (
        patch(
            "custom.sink.deferred_tasks.dispatch_next",
            return_value=False,
        ),
        patch("custom.sink.deferred_tasks.time.sleep"),
        patch("custom.sink.deferred_tasks.request_tui_exit") as exit_req,
    ):
        _advance_after_hard_end(tasker, 3, "每周逆袭悬赏", outcome="Failed")

    exit_req.assert_called_once_with("managed_task_hard_end")
    _reset()
