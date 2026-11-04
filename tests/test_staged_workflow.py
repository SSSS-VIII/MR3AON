from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custom.staged_workflow import Stage, StageStore
from custom import staged_workflow as state
from custom.action.staged_workflow import BeginWorkflowStage, CompleteWorkflowStage, pause_workflow
from custom.deferred_tasks import managed_task_queue, ManagedTask


def test_progress_survives_reopen_and_never_replays_a_completed_stage(tmp_path):
    path = tmp_path / "progress.json"
    stage = Stage("tutorial", "account-a", "1", 1)
    store = StageStore(path)
    assert store.begin(stage)
    store.mark(stage, "completed")
    assert not StageStore(path).begin(stage, retry=True)
    assert StageStore(path).begin(replace(stage, number=2))
    assert StageStore(path).begin(replace(stage, account="account-b"))
    assert StageStore(tmp_path / "other-instance.json").begin(stage)
    with pytest.raises(ValueError, match="其它版本"):
        store.begin(replace(stage, revision="2"))


def test_crashed_and_paused_stages_require_explicit_retry(tmp_path):
    store = StageStore(tmp_path / "state.json")
    stage = Stage("tutorial", "account", "1", 5)
    assert store.begin(stage)
    with pytest.raises(ValueError, match="显式"):
        StageStore(store.path).begin(stage)
    store.mark(stage, "paused", reason="wrong page")
    with pytest.raises(ValueError):
        store.begin(stage)
    assert store.begin(stage, retry=True)
    store.mark(stage, "completed")
    with pytest.raises(ValueError):
        store.mark(stage, "paused")


def test_corrupt_progress_is_not_overwritten(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('broken')
    with pytest.raises(ValueError):
        StageStore(p).begin(Stage("tutorial", "a", "1", 1))
    assert p.read_text() == 'broken'


def test_unknown_persisted_status_cannot_be_treated_as_a_new_stage(tmp_path):
    p = tmp_path / 'state.json'
    stage = Stage('tutorial', 'account', '1', 1)
    store = StageStore(p)
    store.begin(stage)
    data = json.loads(p.read_text())
    next(iter(data['workflows'].values()))['stages']['1']['status'] = 'unknown'
    p.write_text(json.dumps(data))
    before = p.read_bytes()
    with pytest.raises(ValueError, match='状态损坏'):
        store.begin(stage, retry=True)
    assert p.read_bytes() == before


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    managed_task_queue.finish()
    store = StageStore(tmp_path / "state.json")
    monkeypatch.setattr(state, "stage_store", store)
    nodes = {
        "config": {"attach": {"account": "test-account"}},
        "entry": {"attach": {"workflow": "tutorial"}},
    }
    context = SimpleNamespace(
        get_node_data=nodes.get, override_pipeline=lambda value: True,
        override_next=lambda name, value: True,
    )
    argv = SimpleNamespace(task_detail=SimpleNamespace(task_id=123), node_name="entry", custom_action_param={
        "workflow": "tutorial", "revision": "1", "stage": 1,
        "config_node": "config", "failure_node": "pause", "skip_node": "skip",
    })
    yield context, argv, store, nodes
    state.forget_stage(123)
    managed_task_queue.finish()


def test_stage_actions_record_success_and_skip_on_restart(workflow):
    context, argv, store, nodes = workflow
    assert BeginWorkflowStage().run(context, argv).success
    assert CompleteWorkflowStage().run(context, argv).success
    with patch.object(context, "override_next") as skip:
        skip.return_value = True
        assert BeginWorkflowStage().run(context, argv).success
        skip.assert_called_once_with("entry", ["skip"])
    assert not state.stage_is_guarded(123)


def test_failure_discards_remaining_stages_without_recording_success(workflow):
    context, argv, store, nodes = workflow
    managed_task_queue.activate([ManagedTask("stage", "entry", {})], 123)
    assert BeginWorkflowStage().run(context, argv).success
    with patch('custom.action.staged_workflow.request_tui_exit') as exit_tui:
        assert pause_workflow(123, "lost page")
        exit_tui.assert_called_once()
    assert not managed_task_queue.has_pending()
    data = json.loads(store.path.read_text())
    assert next(iter(data["workflows"].values()))["stages"]["1"]["status"] == "paused"


def test_mixed_daily_plan_and_missing_account_are_rejected(workflow):
    context, argv, store, nodes = workflow
    managed_task_queue.activate([ManagedTask("daily", "daily-entry", {})], 123)
    assert not BeginWorkflowStage().run(context, argv).success
    assert not store.path.exists()
    managed_task_queue.finish()
    nodes["config"]["attach"]["account"] = ""
    assert not BeginWorkflowStage().run(context, argv).success
    assert not store.path.exists()


@pytest.mark.parametrize("outcome", ["Failed", "Succeeded"])
def test_hard_end_cannot_silently_advance_to_the_next_stage(workflow, outcome):
    from custom.sink.deferred_tasks import _advance_after_hard_end
    context, argv, store, nodes = workflow
    task = ManagedTask("stage", "entry", {})
    managed_task_queue.activate([task], 123)
    managed_task_queue.set_current(123, task)
    assert BeginWorkflowStage().run(context, argv).success
    with patch('custom.action.staged_workflow.request_tui_exit'), patch('custom.sink.deferred_tasks.dispatch_next') as dispatch:
        _advance_after_hard_end(None, 123, "entry", outcome=outcome)
        dispatch.assert_not_called()
    assert not managed_task_queue.has_pending()


def test_wrapper_finalize_cannot_bypass_stage_completion(workflow):
    from custom.action.deferred_tasks import ManagedTaskSchedulerFinalize
    context, argv, store, nodes = workflow
    assert BeginWorkflowStage().run(context, argv).success
    with patch('custom.action.staged_workflow.request_tui_exit'), patch('custom.action.deferred_tasks.dispatch_next') as dispatch:
        assert ManagedTaskSchedulerFinalize().run(context, argv).success
        dispatch.assert_not_called()
    data = json.loads(store.path.read_text())
    assert next(iter(data['workflows'].values()))['stages']['1']['status'] == 'paused'


@pytest.mark.parametrize('stages', [[None, 1], [2, 1], [1, 1]])
def test_bootstrap_rejects_mixed_or_out_of_order_plan_before_any_task(stages):
    from custom.action.deferred_tasks import ManagedTaskSchedulerBootstrap
    from unittest.mock import Mock
    nodes = {
        f'entry{i}': {'attach': {'workflow': 'tutorial', 'stage': stage}} if stage is not None else {}
        for i, stage in enumerate(stages)
    }
    context = SimpleNamespace(
        get_node_data=nodes.get, tasker=None,
        override_pipeline=Mock(return_value=True), override_next=Mock(return_value=True),
    )
    argv = SimpleNamespace(node_name='bootstrap', task_detail=SimpleNamespace(task_id=55), custom_action_param={
        'tasks': [{'name': name, 'entry': name} for name in nodes],
    })
    with patch('custom.action.deferred_tasks.persistent_task_state_store.start') as start, patch('custom.action.deferred_tasks.dispatch_next') as dispatch, patch('custom.action.deferred_tasks.request_tui_exit'):
        assert ManagedTaskSchedulerBootstrap().run(context, argv).success
        start.assert_not_called()
        dispatch.assert_not_called()
        context.override_next.assert_called_once_with('bootstrap', ['AgentSchedulerRejectedPlan'])


def test_bootstrap_accepts_readme_followed_by_ordered_stages():
    from custom.action.deferred_tasks import ManagedTaskSchedulerBootstrap
    nodes = {
        'readme': {'attach': {'workflow': 'tutorial'}},
        'one': {'attach': {'workflow': 'tutorial', 'stage': 1}},
        'two': {'attach': {'workflow': 'tutorial', 'stage': 2}},
    }
    context = SimpleNamespace(get_node_data=nodes.get, tasker=object())
    argv = SimpleNamespace(node_name='bootstrap', task_detail=SimpleNamespace(task_id=56), custom_action_param={
        'tasks': [{'name': name, 'entry': name} for name in nodes],
    })
    try:
        with patch('custom.action.deferred_tasks.persistent_task_state_store.start'), patch('custom.action.deferred_tasks.persistent_task_state_store.is_enabled', return_value=True), patch('custom.action.deferred_tasks.dispatch_next', return_value=True) as dispatch:
            assert ManagedTaskSchedulerBootstrap().run(context, argv).success
            dispatch.assert_called_once_with(context.tasker)
            assert managed_task_queue.plan_order() == ['readme', 'one', 'two']
    finally:
        managed_task_queue.finish()
