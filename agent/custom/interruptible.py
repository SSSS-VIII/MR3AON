"""可中止点击/睡眠工具

为长时序的自定义动作（如 my_3v3_kn_*）提供"切片轮询 + deadline 校准"的
可中止 sleep 与 click，使得用户在 UI 点击停止任务时，正在阻塞的 Python
点击序列能在一次轮询步长内退出，不再继续后续点击。

设计要点:
- Python 单线程内无法被外部信号打断 ``time.sleep``，只能轮询。
- ``time.sleep`` 在 Windows 上有 ~15ms 调度抖动，朴素切片会让累计抖动
  随片数线性增长。本模块以绝对 deadline 为基准，最后一片自动收尾，
  总耗时与原 ``time.sleep(delay_ms / 1000)`` 同一量级。

在自定义动作里可包一层 ``click``：若 ``interruptible_click`` 返回 False 则抛出
``TaskStopRequested``，由 ``run`` 里 ``except TaskStopRequested`` 返回
``success=False``，主序列仍保持一行 ``click(x, y, t)``。
"""

import time

from maa.context import Context

_DEFAULT_POLL_MS = 100

class TaskStopRequested(Exception):
    """用户在任务运行中请求停止；由可中止 click 包装抛出，run() 捕获后返回 success=False。"""



def is_stopping(context: Context) -> bool:
    try:
        return bool(context.tasker.stopping)
    except Exception:
        return False

#点击延迟校准 - 只需要校准一次
def click_delay_calibrate() -> int:
    return 500

# ADB 点击提交和等待返回的固定耗时估计。
CLICK_SUBMIT_COST = 38


class ClickDelayState:
    """维护一段连续点击序列尚未偿还的 ADB 耗时。"""

    def __init__(self) -> None:
        self.debt_ms = 0

    def compensate(self, delay_ms: int) -> int:
        """扣除本次点击耗时及历史欠账，返回本次实际需要 sleep 的时长。"""
        remaining_ms = delay_ms - CLICK_SUBMIT_COST - self.debt_ms
        if remaining_ms >= 0:
            self.debt_ms = 0
            return remaining_ms

        self.debt_ms = -remaining_ms
        return 0

def interruptible_sleep(
    context: Context, delay_ms: int, poll_ms: int = _DEFAULT_POLL_MS
) -> bool:
    """切片睡眠 + deadline 校准。

    返回 ``True`` 表示正常睡完未被打断；返回 ``False`` 表示中途检测到
    ``tasker.stopping``，调用方应立即提前返回。
    """
    if delay_ms <= 0:
        return not is_stopping(context)

    deadline = time.monotonic() + delay_ms / 1000.0
    step = poll_ms / 1000.0
    while True:
        if is_stopping(context):
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return not is_stopping(context)
        time.sleep(remaining if remaining < step else step)


def interruptible_click(
    context: Context,
    x: int,
    y: int,
    delay_ms: int = 0,
    poll_ms: int = _DEFAULT_POLL_MS,
    delay_state: ClickDelayState | None = None,
) -> bool:
    """可中止的"点击 + 延迟"。

    返回 ``True`` 表示点击与延迟均完成；返回 ``False`` 表示动作前/后/
    延迟期间检测到停止信号，调用方应立即提前返回。
    """
    if is_stopping(context):
        return False
    context.tasker.controller.post_click(x, y).wait()
    if is_stopping(context):
        return False
    if delay_state is not None:
        delay_ms = delay_state.compensate(delay_ms)
    return interruptible_sleep(context, delay_ms, poll_ms)
