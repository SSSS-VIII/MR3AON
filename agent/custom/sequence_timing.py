"""可复用的关卡动作时序，不隐式套用3v3的固定修正。"""
from __future__ import annotations

import time

from custom.interruptible import TaskStopRequested, interruptible_sleep, is_stopping


def bind_sequence_clicks(
    context, *, timing_mode="post_click", initial_delay_ms=0, interval_offset_ms=0,
):
    if timing_mode not in ("post_click", "absolute"):
        raise ValueError("未知时序模式")
    if type(initial_delay_ms) is not int or not 0 <= initial_delay_ms <= 10000:
        raise ValueError("首段等待须为0～10000毫秒")
    if type(interval_offset_ms) is not int or not -500 <= interval_offset_ms <= 500:
        raise ValueError("动作间隔偏移须为-500～500毫秒")
    started = False
    deadline = None

    def click(x, y, delay_ms=0):
        nonlocal started, deadline
        if any(type(value) is not int for value in (x, y, delay_ms)):
            raise ValueError("坐标和等待必须为整数")
        if not 0 <= x < 1280 or not 0 <= y < 720 or delay_ms < 0:
            raise ValueError("关卡点击超出1280×720范围或等待为负")
        if is_stopping(context):
            raise TaskStopRequested
        if not started:
            if not interruptible_sleep(context, initial_delay_ms):
                raise TaskStopRequested
            started = True
        click_started = time.monotonic()
        context.tasker.controller.post_click(x, y).wait()
        if is_stopping(context):
            raise TaskStopRequested
        delay = max(0, delay_ms + interval_offset_ms)
        if timing_mode == "absolute":
            deadline = (click_started if deadline is None else deadline) + delay / 1000
            delay = max(0, (deadline - time.monotonic()) * 1000)
        if not interruptible_sleep(context, delay):
            raise TaskStopRequested

    return click


def bind_stage_clicks(context, task_id):
    from custom.staged_workflow import active_stage
    stage = active_stage(task_id)
    if stage is None:
        raise ValueError("关卡动作缺少工作流账号与阶段上下文")
    return bind_sequence_clicks(
        context, timing_mode=stage.timing_mode,
        initial_delay_ms=stage.initial_delay_ms,
        interval_offset_ms=stage.interval_offset_ms,
    )
