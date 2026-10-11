"""把当前 pipeline 节点名推给 TUI，并维护全局识别成功状态。

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
        if noti_type == NotificationType.Starting and detail.name:
            names = [attr.name for attr in (detail.next_list or []) if attr.name]
            runtime_status.note_next_list_starting(detail.name, names)
            return
        if noti_type in (NotificationType.Succeeded, NotificationType.Failed):
            runtime_status.note_next_list_finished()

    def on_node_recognition(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodeRecognitionDetail,
    ) -> None:
        if noti_type == NotificationType.Succeeded and detail.name:
            runtime_status.note_recognition_succeeded(detail.name)
            # 奖励截图等：同 next 列表命中其它候选时打断连续入口
            from custom.reward_shots import on_recognition_succeeded

            on_recognition_succeeded(detail.name)

    def on_node_action(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodeActionDetail,
    ) -> None:
        # 动作开始即表示识别已命中并进入该节点
        if noti_type == NotificationType.Starting and detail.name:
            runtime_status.set_node(detail.name)
