"""在业务流水线停止当前 task 前推进 Agent 管理的队列。"""

from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context, ContextEventSink
from maa.event_sink import NotificationType

from custom.action.deferred_tasks import dispatch_next
from custom.deferred_tasks import managed_task_queue
from utils.logger import logger


def _action_type(action: Any) -> str | None:
    if isinstance(action, str):
        return action
    if isinstance(action, dict):
        value = action.get("type")
        return value if isinstance(value, str) else None
    return None


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

        current = managed_task_queue.current()
        entry = current.entry if current is not None else detail.name
        logger.info(
            f"Agent 收到任务结束通知: task_id={detail.task_id}, "
            f"entry={entry!r}, stop_node={detail.name!r}"
        )
        if not dispatch_next(context.tasker):
            logger.error(
                f"Agent 在 StopTask 前提交下一项失败: "
                f"task_id={detail.task_id}, stop_node={detail.name!r}"
            )
