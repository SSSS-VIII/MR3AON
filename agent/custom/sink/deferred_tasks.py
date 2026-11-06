"""在业务流水线停止当前 task 前推进 Agent 管理的队列。

硬失败（Task.Failed）不会走到 StopTask，必须另开线程推进；Tasker 回调里
不能直接 post_task（会插进别的 RPC，见 tasker-sink-ipc-stack 记录）。
"""

from __future__ import annotations

import threading
import time
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context, ContextEventSink
from maa.event_sink import NotificationType
from maa.tasker import Tasker, TaskerEventSink

from custom.action.deferred_tasks import dispatch_next
from custom.deferred_tasks import managed_task_queue
from runtime.run_result import invocation_result
from tui.run import request_tui_exit
from utils.logger import logger


def _action_type(action: Any) -> str | None:
    if isinstance(action, str):
        return action
    if isinstance(action, dict):
        value = action.get("type")
        return value if isinstance(value, str) else None
    return None


def _advance_after_hard_end(
    tasker: Tasker,
    task_id: int,
    entry: str,
    *,
    outcome: str,
) -> None:
    """等 Tasker 回调栈退干净后再调度，避免 send_and_recv 重入。"""
    # 给 Failed/Succeeded 通知完全返回留一点时间
    time.sleep(0.05)
    if managed_task_queue.active_for(task_id):
        from custom.action.staged_workflow import pause_workflow
        if pause_workflow(task_id, f"阶段异常结束：{outcome}"):
            return
    abandoned = managed_task_queue.abandon_current(task_id)
    if abandoned is None:
        # StopTask 路径已 release+dispatch，或队列已切到下一项
        return

    invocation_result.record("failed", f"managed_task_hard_end:{outcome}:{abandoned.entry}")
    logger.error(
        f"Agent 管理的任务硬结束({outcome}): task_id={task_id}, "
        f"entry={entry!r}, name={abandoned.name!r}；尝试推进队列"
    )
    try:
        ok = dispatch_next(tasker)
    except Exception as exc:
        logger.exception(
            f"Agent 硬结束后推进队列异常: task_id={task_id}, entry={entry!r}: {exc}"
        )
        request_tui_exit("managed_task_hard_end")
        return

    if not ok:
        logger.error(
            f"Agent 硬结束后推进队列失败: task_id={task_id}, entry={entry!r}"
        )
        request_tui_exit("managed_task_hard_end")


@AgentServer.context_sink()
class ManagedTaskStopSink(ContextEventSink):
    """StopTask 即将执行时提交下一项，避免 task 结束后 Agent 被回收。"""

    def on_node_action(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodeActionDetail,
    ) -> None:
        if noti_type != NotificationType.Starting:
            return
        if not managed_task_queue.active_for(detail.task_id):
            return

        node_data = context.get_node_data(detail.name)
        if not node_data or _action_type(node_data.get("action")) != "StopTask":
            return

        from custom.action.staged_workflow import pause_workflow
        if pause_workflow(detail.task_id, "阶段未经过成功登记就停止"):
            return

        current = managed_task_queue.current()
        entry = current.entry if current is not None else detail.name
        logger.info(
            f"Agent 收到任务结束通知: task_id={detail.task_id}, "
            f"entry={entry!r}, stop_node={detail.name!r}"
        )
        retained = managed_task_queue.release_recurring_current(detail.task_id)
        if retained is not None:
            logger.info(
                f"Agent 已保留下一周期候选: entry={retained.entry!r}, "
                f"not_before={retained.not_before.isoformat()!r}"
            )
        if not dispatch_next(context.tasker):
            invocation_result.record("failed", "stop_dispatch_failed")
            logger.error(
                f"Agent 在 StopTask 前提交下一项失败: "
                f"task_id={detail.task_id}, stop_node={detail.name!r}"
            )


@AgentServer.tasker_sink()
class ManagedTaskHardEndSink(TaskerEventSink):
    """StopTask 未走到时（Failed / 异常 Succeeded）推进队列或退出 TUI。"""

    def on_tasker_task(
        self,
        tasker: Tasker,
        noti_type: NotificationType,
        detail: TaskerEventSink.TaskerTaskDetail,
    ) -> None:
        if noti_type not in (NotificationType.Failed, NotificationType.Succeeded):
            return
        if detail.entry == "MaaTaskerPostStop":
            return
        if not managed_task_queue.active_for(detail.task_id):
            return

        outcome = "Failed" if noti_type == NotificationType.Failed else "Succeeded"
        threading.Thread(
            target=_advance_after_hard_end,
            args=(tasker, detail.task_id, detail.entry),
            kwargs={"outcome": outcome},
            name=f"maa-managed-hard-end-{detail.task_id}",
            daemon=True,
        ).start()
