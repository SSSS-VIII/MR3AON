from types import SimpleNamespace

import pytest

from custom import sequence_timing as timing
from custom.interruptible import TaskStopRequested


@pytest.fixture
def clocked(monkeypatch):
    clock = SimpleNamespace(now=0.0, clicks=[], sleeps=[])
    tasker = SimpleNamespace(stopping=False)
    def post_click(x, y):
        clock.clicks.append((x, y, clock.now))
        def wait():
            clock.now += .04
        return SimpleNamespace(wait=wait)
    tasker.controller = SimpleNamespace(post_click=post_click)
    def sleep(context, ms):
        clock.sleeps.append(ms)
        clock.now += ms / 1000
        return not tasker.stopping
    monkeypatch.setattr(timing.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(timing, "interruptible_sleep", sleep)
    return SimpleNamespace(tasker=tasker), clock


@pytest.mark.parametrize("mode, expected", [("post_click", .28), ("absolute", .2)])
def test_input_cost_is_only_subtracted_in_absolute_mode(clocked, mode, expected):
    context, clock = clocked
    click = timing.bind_sequence_clicks(context, timing_mode=mode)
    click(100, 100, 100)
    click(200, 200, 100)
    assert clock.now == pytest.approx(expected)  # 没有隐式+60ms


def test_initial_delay_once_and_explicit_interval_offset(clocked):
    context, clock = clocked
    click = timing.bind_sequence_clicks(context, initial_delay_ms=20, interval_offset_ms=-10)
    click(100, 100, 100)
    click(200, 200, 100)
    assert clock.clicks[0][2] == .02
    assert clock.now == pytest.approx(.28)
    assert clock.sleeps == [20, 90, 90]


def test_stop_and_invalid_arguments_cannot_send_input(clocked):
    context, clock = clocked
    click = timing.bind_sequence_clicks(context)
    context.tasker.stopping = True
    with pytest.raises(TaskStopRequested):
        click(100, 100, 100)
    context.tasker.stopping = False
    for args in [(1280, 0, 0), (0, -1, 0), (0, 0, -1), (True, 0, 0)]:
        with pytest.raises(ValueError):
            click(*args)
    assert not clock.clicks
