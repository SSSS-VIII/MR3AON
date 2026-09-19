"""识别：游戏曾经活过之后进程消失（闪退）。"""

from __future__ import annotations

from typing import Optional, Union

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType

from custom.game_process_watch import game_process_watch
from utils.adb_device import pidof_package
from utils.logger import logger


def _resolve_package(context: Context) -> Optional[str]:
    from custom.action.general import (
        _get_remembered_game_package,
        _get_start_app_package,
    )

    package = _get_remembered_game_package()
    if package:
        return package
    return _get_start_app_package(context)


def check_game_crash(context: Context) -> Optional[str]:
    """若判定闪退则返回 package，否则 None。可被识别与 sink 共用。"""
    if not game_process_watch.watching:
        return None

    package = _resolve_package(context)
    if not package:
        return None

    pid = pidof_package(package)
    if pid:
        game_process_watch.note_present()
        return None

    # 还没见过活进程：只是尚未拉起成功，不算闪退。
    if not game_process_watch.seen_alive:
        return None

    if not game_process_watch.note_missing():
        return None

    return package


@AgentServer.custom_recognition("GameProcessMissing")
class GameProcessMissing(CustomRecognition):
    """持续检查：进程曾出现过后又连续找不到，才判定闪退。"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        try:
            package = check_game_crash(context)
            if not package:
                return None

            logger.warning(
                f"GameProcessMissing: 判定闪退 package={package!r} "
                f"(seen_alive 后进程消失)"
            )
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 1, 1],
                detail={"package": package, "crashed": True},
            )
        except Exception as exc:
            logger.exception(f"GameProcessMissing 失败: {exc}")
            return None


@AgentServer.custom_recognition("WaydroidRestartRequested")
class WaydroidRestartRequested(CustomRecognition):
    """启动入口：若已挂起“需要重启 Waydroid”则命中。"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        if game_process_watch.peek_waydroid_restart_request():
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 1, 1],
                detail={"restart_requested": True},
            )
        return None
