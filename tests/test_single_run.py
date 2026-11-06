from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom.action import deferred_tasks as scheduler
from custom.deferred_tasks import ManagedTask, deferred_task_store, managed_task_queue, managed_task_yield_signal_store
from custom.persistent_task_state import PersistentTaskStateStore
from custom.sink.deferred_tasks import _advance_after_hard_end
from runtime import run_result
from tui.status import runtime_status


@pytest.fixture
def once(tmp_path, monkeypatch):
    result = tmp_path / 'result.json'
    monkeypatch.setenv('MR3A_RUN_ONCE', '1')
    monkeypatch.setenv('MR3A_RUN_RESULT', str(result))
    state = PersistentTaskStateStore(tmp_path / 'state.json')
    monkeypatch.setattr(scheduler, 'persistent_task_state_store', state)
    monkeypatch.setattr(run_result.invocation_result, '_result', None)
    managed_task_queue.finish()
    deferred_task_store.clear()
    runtime_status.clear_exit_request()
    yield result, state
    state.stop()
    managed_task_queue.finish()
    deferred_task_store.clear()
    managed_task_yield_signal_store.clear()
    runtime_status.clear_exit_request()


def argv(param, task_id=7):
    return SimpleNamespace(custom_action_param=param, task_detail=SimpleNamespace(task_id=task_id))


def tasker():
    return SimpleNamespace(stopping=False, post_task=Mock(return_value=SimpleNamespace(job_id=7)))


def activate(entry='T'):
    managed_task_queue.activate([ManagedTask('T', entry, {})], 1)
    managed_task_queue.set_current(7, managed_task_queue.pop_pending())


def test_already_completed_task_exits_without_waiting(once):
    result, state = once
    state.set('T', enabled=False, valid_until=datetime.now().astimezone() + timedelta(days=1))
    context = SimpleNamespace(tasker=tasker())
    outcome = scheduler.ManagedTaskSchedulerBootstrap().run(context, argv({'tasks': [{'name': 'T', 'entry': 'T'}]}))
    assert outcome.success
    context.tasker.post_task.assert_not_called()
    assert json.loads(result.read_text())['status'] == 'skipped'
    assert not managed_task_queue.has_pending()


def test_completion_is_persisted_without_retaining_next_cycle(once):
    result, state = once
    activate()
    complete = scheduler.SetManagedTaskPersistentState().run(None, argv({'enabled': False, 'valid_until': 'next_daily_reset'}))
    assert complete.success
    assert not state.is_enabled('T')
    assert managed_task_queue.release_recurring_current(7) is None
    context = SimpleNamespace(tasker=tasker())
    assert scheduler.ManagedTaskSchedulerFinalize().run(context, argv({})).success
    context.tasker.post_task.assert_not_called()
    assert json.loads(result.read_text())['exit_code'] == 0


def test_periodic_deferral_returns_incomplete_without_arming_timer(once):
    result, _ = once
    activate()
    outcome = scheduler.ScheduleDeferredTask().run(None, argv({'key': 'later', 'entry': 'T', 'daily_times': ['20:00']}))
    assert outcome.success
    assert not deferred_task_store.snapshot()
    assert scheduler.dispatch_next(tasker())
    assert json.loads(result.read_text())['exit_code'] == 3


def test_hourly_yield_finishes_instead_of_requeueing(once):
    result, _ = once
    activate('每周逆袭悬赏entry')
    assert scheduler._TIME_SLICE_SECONDS['每周逆袭悬赏entry'] == 3600
    assert scheduler.ManagedTaskSchedulerYieldCurrent().run(None, argv({})).success
    assert not managed_task_queue.has_pending()
    assert scheduler.dispatch_next(tasker())
    assert json.loads(result.read_text())['exit_code'] == 4


def test_hard_failure_cannot_be_overwritten_by_queue_finished(once, monkeypatch):
    result, _ = once
    activate()
    monkeypatch.setattr('custom.sink.deferred_tasks.time.sleep', lambda _: None)
    _advance_after_hard_end(tasker(), 7, 'T', outcome='Failed')
    assert json.loads(result.read_text())['status'] == 'failed'
    assert json.loads(result.read_text())['exit_code'] == 1


def test_error_exit_and_user_quit_have_distinct_results(once):
    result, _ = once
    run_result.invocation_result.on_exit('user_quit')
    assert json.loads(result.read_text())['exit_code'] == 130
    run_result.invocation_result.on_exit('abort_tasker')
    run_result.invocation_result.on_exit('queue_finished')
    assert json.loads(result.read_text())['exit_code'] == 1
