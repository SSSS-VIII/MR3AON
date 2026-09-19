"""任务运行期间持续检查游戏进程是否闪退。

只做节流后的 pidof。命中后只挂起恢复标志，真正重启 Waydroid 由流水线节点执行，
避免在回调里阻塞或 post().wait() 死锁。
"""

from __future__ import annotations

import threading

from maa.agent.agent_server import AgentServer
from maa.context import Context, ContextEventSink
from maa.event_sink import NotificationType

from custom.game_process_watch import game_process_watch
from custom.reco.game_process_missing import check_game_crash
from utils.logger import logger

_RECOVERY_NODE = "处理游戏闪退"


@AgentServer.context_sink()
class GameProcessWatchSink(ContextEventSink):
    """识别回调上最多每几秒 pidof 一次；进程曾出现后又消失才算闪退。"""

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()

    def on_node_recognition(
        self,
        context: Context,
        noti_type: NotificationType,
        detail: ContextEventSink.NodeRecognitionDetail,
    ) -> None:
        if noti_type not in (
            NotificationType.Succeeded,
            NotificationType.Failed,
        ):
            return
        if not game_process_watch.should_poll():
            return
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._maybe_mark_crash(context, noti_type, detail)
        finally:
            self._lock.release()

    def _maybe_mark_crash(self, context, noti_type, detail) -> None:
        try:
            if context.tasker.stopping:
                return
        except Exception:
            return

        package = check_game_crash(context)
        if not package:
            return
        if not game_process_watch.begin_recovery():
            return

        logger.error(
            f"GameProcessWatchSink: 检测到闪退 package={package!r}, "
            f"task_id={detail.task_id}, node={detail.name!r}"
        )
        # 当前节点若会继续往下走，直接改道。全 miss 时由启动流程 / Default_on_error
        # 里的「处理游戏闪退」在下一轮吃掉标志。
        if noti_type == NotificationType.Succeeded:
            try:
                context.override_next(detail.name, [_RECOVERY_NODE])
            except Exception as exc:
                logger.exception(
                    f"GameProcessWatchSink: 改道失败 node={detail.name!r}: {exc}"
                )
