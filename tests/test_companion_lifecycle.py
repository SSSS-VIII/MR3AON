"""协同环境必须随所属顶层任务收尾，迟到回调不能碰新的持有者。"""
import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from maa.event_sink import NotificationType

from custom.action import deferred_tasks as scheduler
from custom.action import general
from custom.deferred_tasks import ManagedTask, managed_task_queue
from custom.sink import deferred_tasks as sinks
from runtime import companion, run_result


class OwnedCompanion:
    def __init__(self, owner=11):
        self.owner = owner
        self.requests = []

    def stop(self, task_id=None, wait=False):
        self.requests.append((task_id, wait))
        if task_id == self.owner:
            self.owner = None


@pytest.fixture
def managed(monkeypatch):
    manager = OwnedCompanion()
    monkeypatch.setattr(companion, "companion_manager", manager)
    monkeypatch.setattr("custom.action.staged_workflow.pause_workflow", lambda *_: False)
    monkeypatch.setattr(sinks.time, "sleep", lambda _: None)
    monkeypatch.setattr(run_result.invocation_result, "record", Mock())
    managed_task_queue.finish()
    managed_task_queue.activate([ManagedTask("每日悬赏", "每日悬赏entry", {})], 1)
    managed_task_queue.set_current(11, managed_task_queue.pop_pending())
    yield manager
    managed_task_queue.finish()


def arguments(task_id=11):
    return SimpleNamespace(
        custom_action_param={},
        task_detail=SimpleNamespace(task_id=task_id, entry="AgentSchedulerTaskWrapper"),
    )


def context():
    return SimpleNamespace(
        tasker=SimpleNamespace(stopping=False),
        get_node_data=lambda _: {"action": {"type": "StopTask"}},
    )


@pytest.mark.parametrize("ending", ["stop", "finalize", "failed", "unexpected_success"])
def test_task_releases_companion_before_dispatch(managed, monkeypatch, ending):
    dispatched = []

    def dispatch(tasker):
        assert managed.owner is None
        dispatched.append(tasker)
        managed_task_queue.set_current(22, ManagedTask("next", "N", {}))
        return True

    monkeypatch.setattr(scheduler, "dispatch_next", dispatch)
    monkeypatch.setattr(sinks, "dispatch_next", dispatch)
    ctx = context()
    if ending == "stop":
        sinks.ManagedTaskStopSink().on_node_action(
            ctx, NotificationType.Starting, SimpleNamespace(task_id=11, name="stop")
        )
    elif ending == "finalize":
        assert scheduler.ManagedTaskSchedulerFinalize().run(ctx, arguments()).success
    else:
        sinks._advance_after_hard_end(
            ctx.tasker, 11, "AgentSchedulerTaskWrapper",
            outcome="Failed" if ending == "failed" else "Succeeded",
        )
    assert len(dispatched) == 1
    assert managed.requests == [(11, False)]


@pytest.mark.parametrize("ending", ["stop", "finalize", "failed", "tasker_sink"])
def test_late_old_task_cannot_release_new_companion(managed, monkeypatch, ending):
    managed.owner = 22
    managed_task_queue.set_current(22, ManagedTask("new", "每日悬赏entry", {}))
    dispatch = Mock(return_value=True)
    monkeypatch.setattr(scheduler, "dispatch_next", dispatch)
    monkeypatch.setattr(sinks, "dispatch_next", dispatch)
    ctx = context()
    if ending == "stop":
        sinks.ManagedTaskStopSink().on_node_action(
            ctx, NotificationType.Starting, SimpleNamespace(task_id=11, name="stop")
        )
    elif ending == "finalize":
        assert scheduler.ManagedTaskSchedulerFinalize().run(ctx, arguments()).success
    elif ending == "failed":
        sinks._advance_after_hard_end(ctx.tasker, 11, "old", outcome="Failed")
    else:
        sinks.ManagedTaskHardEndSink().on_tasker_task(
            ctx.tasker, NotificationType.Failed,
            SimpleNamespace(task_id=11, entry="old"),
        )
    assert managed.owner == 22
    dispatch.assert_not_called()
    assert all(task_id == 11 and not wait for task_id, wait in managed.requests)


@pytest.mark.parametrize("recovery", ["home", "restart", "yield"])
def test_requeue_releases_old_owner_even_when_current_is_cleared(managed, monkeypatch, recovery):
    ctx = context()
    monkeypatch.delenv("MR3A_RUN_ONCE", raising=False)
    if recovery == "home":
        result = general.RetryCurrentTaskAtHome().run(ctx, arguments())
    elif recovery == "restart":
        monkeypatch.setattr(general, "_get_remembered_game_package", lambda: "test.package")
        monkeypatch.setattr(general.game_process_watch, "disarm", lambda: None)
        ctx.tasker.controller = SimpleNamespace(
            post_stop_app=Mock(return_value=SimpleNamespace(wait=lambda: None, succeeded=True)),
        )
        result = general.RestartGame().run(ctx, arguments())
    else:
        result = scheduler.ManagedTaskSchedulerYieldCurrent().run(ctx, arguments())
    assert result.success
    assert managed_task_queue.current() is None
    assert managed_task_queue.active_for(11)
    assert managed.owner is None
    assert managed.requests == [(11, False)]
    dispatched = Mock(return_value=True)
    monkeypatch.setattr(sinks, "dispatch_next", dispatched)
    sinks.ManagedTaskStopSink().on_node_action(
        ctx, NotificationType.Starting, SimpleNamespace(task_id=11, name="stop")
    )
    dispatched.assert_called_once_with(ctx.tasker)


def test_abort_starts_cleanup_even_if_stop_request_fails(managed):
    ctx = context()
    ctx.tasker.post_stop = Mock(side_effect=RuntimeError("disconnected"))
    assert not general.AbortTasker().run(ctx, arguments()).success
    assert managed.owner is None
    assert managed.requests == [(11, False)]


def test_cleanup_exception_does_not_block_main_dispatch(managed, monkeypatch):
    monkeypatch.setattr(managed, "stop", Mock(side_effect=RuntimeError("cleanup failed")))
    dispatch = Mock(return_value=True)
    monkeypatch.setattr(scheduler, "dispatch_next", dispatch)
    ctx = context()
    assert scheduler.ManagedTaskSchedulerFinalize().run(ctx, arguments()).success
    dispatch.assert_called_once_with(ctx.tasker)


def load_agent_function(monkeypatch, *, use_tui=False, close_ok=True, join_error=None, cleanup=True):
    # 只加载实际 agent()，避免 import main 引发 cwd/日志配置和依赖安装副作用。
    source = Path(__file__).parents[1] / "agent/main.py"
    definition = next(node for node in ast.parse(source.read_text()).body
                      if isinstance(node, ast.FunctionDef) and node.name == "agent")
    events = []
    monkeypatch.delenv("MR3A_RUN_CLEANUP_DIR", raising=False)
    manager = SimpleNamespace(
        shutdown=Mock(side_effect=lambda **_: events.append("cleanup") or cleanup),
        stop=Mock(side_effect=lambda: events.append("handoff")),
    )
    monkeypatch.setattr(companion, "companion_manager", manager)
    outcome = SimpleNamespace(record=Mock(), finalize=Mock(side_effect=lambda: events.append("finalized")))
    monkeypatch.setattr(run_result, "invocation_result", outcome)
    server = SimpleNamespace(
        start_up=Mock(), join=Mock(side_effect=join_error),
    )
    monkeypatch.setattr(importlib.import_module("maa.agent.agent_server"), "AgentServer", server)
    monkeypatch.setattr(importlib.import_module("maa.tasker").Tasker, "set_log_dir", Mock())
    monkeypatch.setattr(importlib.import_module("maa.toolkit").Toolkit, "init_option", Mock())
    lifecycle = importlib.import_module("utils.agent_lifecycle")
    monkeypatch.setattr(lifecycle, "guard_agent_process", Mock())
    monkeypatch.setattr(lifecycle, "close_agent_server", Mock(return_value=close_ok))
    tui = importlib.import_module("tui")
    monkeypatch.setattr(tui, "tui_should_run", lambda: use_tui)
    monkeypatch.setattr(tui, "run_agent_tui", Mock())
    monkeypatch.setattr(tui, "request_tui_exit", Mock())
    monkeypatch.setattr(tui, "terminate_parent_maa_picli", Mock())
    monkeypatch.setattr(importlib.import_module("tui.run"), "request_parent_maa_picli_stop", Mock())
    monkeypatch.setattr(importlib.import_module("tui.status"), "runtime_status",
                        SimpleNamespace(snapshot=lambda: {"exit_reason": "user_quit"}))
    namespace = {
        "logger": Mock(),
        "sys": SimpleNamespace(argv=["main.py", "socket"], stderr=Mock()),
        "os": SimpleNamespace(environ=__import__("os").environ,
                              _exit=Mock(side_effect=lambda _: events.append("forced_exit"))),
        "get_runtime_paths": lambda: SimpleNamespace(debug_dir="/tmp", work_root="/tmp"),
    }
    exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), "exec"), namespace)
    return namespace["agent"], manager, outcome, events


@pytest.mark.parametrize("use_tui", [False, True])
def test_agent_completion_and_q_cleanup_precede_final_result(monkeypatch, use_tui):
    agent, manager, outcome, events = load_agent_function(monkeypatch, use_tui=use_tui)
    agent()
    manager.shutdown.assert_called_once_with(timeout=5)
    assert events == ["cleanup", "finalized"]
    outcome.record.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("disconnect"), KeyboardInterrupt()])
def test_agent_exception_still_reclaims_companion(monkeypatch, error):
    agent, manager, outcome, events = load_agent_function(monkeypatch, join_error=error)
    with pytest.raises(type(error)):
        agent()
    manager.shutdown.assert_called_once_with(timeout=5)
    assert events == ["cleanup"]
    outcome.finalize.assert_not_called()


def test_native_shutdown_timeout_cleans_before_forced_exit(monkeypatch):
    agent, manager, outcome, events = load_agent_function(monkeypatch, close_ok=False)
    agent()
    assert events == ["cleanup", "forced_exit"]
    outcome.record.assert_called_once_with("failed", "agent_shutdown_timeout")
    outcome.finalize.assert_not_called()


@pytest.mark.parametrize("cleanup", [False, RuntimeError("worker error")])
def test_cleanup_failure_cannot_report_success(monkeypatch, cleanup):
    agent, manager, outcome, events = load_agent_function(monkeypatch, cleanup=cleanup)
    if isinstance(cleanup, Exception):
        manager.shutdown.side_effect = cleanup
    agent()
    outcome.record.assert_called_once_with(
        "failed", "companion_shutdown_failed" if isinstance(cleanup, Exception) else "companion_cleanup_incomplete"
    )
    outcome.finalize.assert_called_once()


def test_single_run_hands_cleanup_to_outer_receipt_supervisor(monkeypatch):
    agent, manager, outcome, events = load_agent_function(monkeypatch)
    monkeypatch.setenv("MR3A_RUN_CLEANUP_DIR", "/private/receipts")
    monkeypatch.setenv("MR3A_RUN_ONCE", "1")
    agent()
    manager.stop.assert_called_once_with()
    manager.shutdown.assert_not_called()
    assert events == ["handoff", "finalized"]
    outcome.record.assert_not_called()
