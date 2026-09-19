"""
分辨率检查器

任务开始时确认 Android 逻辑分辨率是 16:9。

Tasker 事件由 MaaPiCli 用 send() 塞进 Agent 当前正在等的那次 RPC。
这里如果再访问 tasker.controller / post_screencap / post_stop，内层
send_and_recv 会把外层回包当成 unexpected msg 丢掉，那一帧就不再返回，
C 栈会一直叠到 RecursionError。所以这里只读 adb wm size。
"""

from __future__ import annotations

import re

from maa.agent.agent_server import AgentServer
from maa.event_sink import NotificationType
from maa.tasker import Tasker, TaskerEventSink

from utils.adb_device import adb_shell, adb_target
from utils.logger import logger

# 目标宽高比：16:9
TARGET_RATIO = 16.0 / 9.0
# 容差范围（±2%）
TOLERANCE = 0.02

_SIZE_RE = re.compile(r"(\d+)\s*x\s*(\d+)", re.IGNORECASE)
_blocked = False


def is_aspect_ratio_16x9(width: int, height: int) -> bool:
    """
    检查给定的尺寸是否大约为 16:9
    同时处理横屏（16:9）和竖屏（9:16）方向
    """
    if width <= 0 or height <= 0:
        return False

    ratio = calculate_aspect_ratio(width, height)

    # 检查比例是否在 16:9 的容差范围内
    return abs(ratio - TARGET_RATIO) <= TARGET_RATIO * TOLERANCE


def calculate_aspect_ratio(width: int, height: int) -> float:
    """
    计算宽高比，始终返回 较大/较小 的比值
    这样可以统一处理横屏和竖屏方向
    """
    w = float(width)
    h = float(height)

    # 始终返回较大值/较小值，以统一方向
    if w > h:
        return w / h
    return h / w


def aspect_ratio_blocked() -> bool:
    return _blocked


def logical_display_size(wm_size_text: str) -> tuple[int, int] | None:
    """Override size 才是脚本看到的分辨率；没有覆写时用 Physical size。"""
    override: tuple[int, int] | None = None
    physical: tuple[int, int] | None = None
    for line in wm_size_text.splitlines():
        match = _SIZE_RE.search(line)
        if match is None:
            continue
        pair = (int(match.group(1)), int(match.group(2)))
        if "Override size" in line:
            override = pair
        elif "Physical size" in line:
            physical = pair
    return override or physical


def _mark_blocked(width: int, height: int) -> None:
    global _blocked
    _blocked = True
    actual_ratio = calculate_aspect_ratio(width, height)
    logger.error(
        f"分辨率比例不匹配，后续调度将停止。"
        f"当前: {width}x{height} (比例: {actual_ratio:.4f})，"
        f"MR3A 仅支持 16:9 比例，请调整为: 2560x1440, 1920x1080, 1600x900, 1280x720 (推荐)"
    )


@AgentServer.tasker_sink()
class AspectRatioChecker(TaskerEventSink):
    """任务开始时用 adb 读 wm size，不调用任何 Maa API。"""

    def on_tasker_task(
        self,
        tasker: Tasker,
        noti_type: NotificationType,
        detail: TaskerEventSink.TaskerTaskDetail,
    ):
        del tasker
        if noti_type != NotificationType.Starting:
            return
        if detail.entry == "MaaTaskerPostStop":
            return
        if _blocked:
            return

        logger.debug(
            f"任务开始前检查分辨率 - task_id: {detail.task_id}, entry: {detail.entry}"
        )
        try:
            adb, serial = adb_target()
            text = adb_shell(adb, serial, "wm", "size", wait_sec=10)
        except Exception as exc:
            logger.error(f"无法读取 wm size，跳过本轮分辨率检查: {exc}")
            return

        size = logical_display_size(text)
        if size is None:
            logger.error(f"wm size 没有解析出分辨率: {text!r}")
            return

        width, height = size
        logger.debug(f"逻辑分辨率: {width} x {height}")
        if not is_aspect_ratio_16x9(width, height):
            _mark_blocked(width, height)
            return
        logger.debug(f"分辨率检查通过: {width}x{height} (16:9)")
