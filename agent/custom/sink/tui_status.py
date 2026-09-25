"""把当前 pipeline 节点名推给 TUI。

只在识别/动作真正命中时更新节点；next 轮询期间显示父节点名。
"""

from __future__ import annotations

from maa.agent.agent_server import AgentServer
from maa.context import Context, ContextEventSink
from maa.event_sink import NotificationType

from tui.status import runtime_status


@AgentServer.context_sink()
class TuiStatusSink(ContextEventSink):
    def on_node_next_list(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodeNextListDetail,
    ) -> None:
        # next 列表开始轮询：展示父节点，而不是每个候选子节点
        if noti_type == NotificationType.Starting and detail.name:
            runtime_status.set_node(detail.name)

    def on_node_recognition(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodeRecognitionDetail,
    ) -> None:
        # 仅命中成功才切换到该节点名
        if noti_type == NotificationType.Succeeded and detail.name:
            runtime_status.set_node(detail.name)

    def on_node_action(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodeActionDetail,
    ) -> None:
        # 动作开始即表示识别已命中并进入该节点
        if noti_type == NotificationType.Starting and detail.name:
            runtime_status.set_node(detail.name)
