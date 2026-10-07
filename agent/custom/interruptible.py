"""可中止点击/睡眠工具

为长时序的自定义动作（如 my_3v3_kn_*）提供可中止的 click 与 sleep，
使得用户在 UI 点击停止任务时，正在阻塞的 Python 点击序列能在一次
轮询步长内退出，不再继续后续点击。

设计要点:
- Python 单线程内无法被外部信号打断 ``time.sleep``，只能轮询。
- ``time.sleep`` 在 Windows 上有 ~15ms 调度抖动，朴素切片会让累计抖动
  随片数线性增长。本模块以绝对 deadline 为基准，最后一片自动收尾，
  总耗时与原 ``time.sleep(delay_ms / 1000)`` 同一量级。

在自定义动作里可包一层 ``click`` / ``doubleclick``：若返回 False 则抛出
``TaskStopRequested``，由 ``run`` 里 ``except TaskStopRequested`` 返回
``success=False``。``doubleclick`` 连点两次、中间不 sleep，整段只走一次
``+60ms`` 时间轴，避免短间隔双击与修正叠出乱序。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from maa.context import Context
from utils.logger import logger

_DEFAULT_POLL_MS = 100
# 原始操作序列的 delay 隐含了作者开发环境中的输入耗时；先补回这一固定
# 差值，再按当前环境每次真实的 controller.wait 耗时动态校准。
# 人手录制（record-3v3-parkour）的按键间隔是 wall-clock，粘贴前须先减去本值，
# 否则每步再 +60，相对录制基线线性变慢；录制脚本导出已自动扣除。
_CLICK_DELAY_CORRECTION_MS = 60

# ADB 点击命令到游戏响应以及首次识图的延迟，只校准一次。
_CLICK_DELAY_CALIBRATION = 350


class TaskStopRequested(Exception):
    """用户在任务运行中请求停止；由可中止 click 包装抛出，run() 捕获后返回 success=False。"""



def is_stopping(context: Context) -> bool:
    try:
        return bool(context.tasker.stopping)
    except Exception:
        return False

# 点击延迟校准 - 只需要校准一次
def click_delay_calibrate() -> int:
    return _CLICK_DELAY_CALIBRATION


class ClickDelayState:
    """维护连续点击序列的绝对时间轴。

    每段按 ``delay_ms + 固定修正值`` 推进。controller.wait 的实际耗时
    从本段剩余时间中动态扣除，某次阻塞过长产生的欠时会由后续间隔偿还。
    """

    def __init__(self) -> None:
        self.index = 0
        self.deadline: float | None = None

    def next_index(self) -> int:
        self.index += 1
        return self.index

    def advance(self, click_started: float, delay_ms: int) -> float:
        if self.deadline is None:
            self.deadline = click_started
        corrected_delay_ms = max(delay_ms + _CLICK_DELAY_CORRECTION_MS, 0)
        self.deadline += corrected_delay_ms / 1000.0
        return self.deadline


def _interruptible_sleep_until(
    context: Context, deadline: float, poll_ms: int = _DEFAULT_POLL_MS
) -> bool:
    step = poll_ms / 1000.0
    while True:
        if is_stopping(context):
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return not is_stopping(context)
        time.sleep(remaining if remaining < step else step)


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
    return _interruptible_sleep_until(context, deadline, poll_ms)


def _finish_click_delay(
    context: Context,
    *,
    label: str,
    x: int,
    y: int,
    click_started: float,
    click_finished: float,
    delay_ms: int,
    poll_ms: int,
    delay_state: ClickDelayState | None,
) -> bool:
    submit_ms = (click_finished - click_started) * 1000.0
    if delay_state is not None:
        deadline = delay_state.advance(click_started, delay_ms)
        remaining_ms = max(0.0, (deadline - click_finished) * 1000.0)
        debt_ms = max(0.0, (click_finished - deadline) * 1000.0)
        logger.info(
            f"3v3 {label}#{delay_state.next_index()}=({x},{y}) "
            f"submit={submit_ms:.1f}ms delay={delay_ms}ms "
            f"correction=+{_CLICK_DELAY_CORRECTION_MS}ms "
            f"sleep<={remaining_ms:.1f}ms debt={debt_ms:.1f}ms"
        )
        return _interruptible_sleep_until(context, deadline, poll_ms)

    logger.info(
        f"{label}=({x},{y}) submit={submit_ms:.1f}ms post_delay={delay_ms}ms"
    )
    return interruptible_sleep(context, delay_ms, poll_ms)


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
    click_started = time.monotonic()
    context.tasker.controller.post_click(x, y).wait()
    click_finished = time.monotonic()
    if is_stopping(context):
        return False
    return _finish_click_delay(
        context,
        label="click",
        x=x,
        y=y,
        click_started=click_started,
        click_finished=click_finished,
        delay_ms=delay_ms,
        poll_ms=poll_ms,
        delay_state=delay_state,
    )


def interruptible_double_click(
    context: Context,
    x: int,
    y: int,
    delay_ms: int = 0,
    poll_ms: int = _DEFAULT_POLL_MS,
    delay_state: ClickDelayState | None = None,
) -> bool:
    """可中止的连点两次 + 一段延迟。

    两次 ``post_click`` 背靠背，中间不插入 sleep；整段只推进一次时间轴
    （含 ``+60ms`` 修正），避免短间隔双击被修正拆成两段乱序。
    """
    if is_stopping(context):
        return False
    click_started = time.monotonic()
    context.tasker.controller.post_click(x, y).wait()
    if is_stopping(context):
        return False
    context.tasker.controller.post_click(x, y).wait()
    click_finished = time.monotonic()
    if is_stopping(context):
        return False
    return _finish_click_delay(
        context,
        label="doubleclick",
        x=x,
        y=y,
        click_started=click_started,
        click_finished=click_finished,
        delay_ms=delay_ms,
        poll_ms=poll_ms,
        delay_state=delay_state,
    )


def bind_parkour_clicks(
    context: Context,
    delay_state: ClickDelayState | None = None,
) -> tuple[Callable[..., None], Callable[..., None]]:
    """给 my_3v3_kn_* 绑定 ``click`` / ``doubleclick`` 本地包装。"""

    def click(x: int, y: int, delay_ms: int = 0) -> None:
        if not interruptible_click(
            context, x, y, delay_ms, delay_state=delay_state
        ):
            raise TaskStopRequested

    def doubleclick(x: int, y: int, delay_ms: int = 0) -> None:
        if not interruptible_double_click(
            context, x, y, delay_ms, delay_state=delay_state
        ):
            raise TaskStopRequested

    return click, doubleclick

