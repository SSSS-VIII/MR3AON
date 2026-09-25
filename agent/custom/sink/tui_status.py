"""把当前 pipeline 节点名推给 TUI。"""

from __future__ import annotations

from maa.agent.agent_server import AgentServer
from maa.context import Context, ContextEventSink
from maa.event_sink import NotificationType

from tui.status import runtime_status


@AgentServer.context_sink()
class TuiStatusSink(ContextEventSink):
    def on_node_recognition(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodeRecognitionDetail,
    ) -> None:
        if noti_type == NotificationType.Starting and detail.name:
            runtime_status.set_node(detail.name)

    def on_node_action(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodeActionDetail,
    ) -> None:
        if noti_type == NotificationType.Starting and detail.name:
            runtime_status.set_node(detail.name)

    def on_node_pipeline_node(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodePipelineNodeDetail,
    ) -> None:
        if noti_type == NotificationType.Starting and detail.name:
            runtime_status.set_node(detail.name)
