"""同一Agent跨周恢复：用真实状态文件、任务计划、完成动作及StopTask调度。"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from maa.event_sink import NotificationType

from custom.action import deferred_tasks as scheduler
import importlib
queue_module = importlib.import_module("custom.deferred_tasks")
from custom.deferred_tasks import managed_task_queue as queue, deferred_task_store
from custom.persistent_task_state import PersistentTaskStateStore
from custom.sink.deferred_tasks import ManagedTaskStopSink

RESOURCE = Path(__file__).resolve().parents[1] / 'assets/resource'
ENTRY = '每周逆袭悬赏entry'
GATES = [f'每周逆袭悬赏阶段{i}进行中' for i in (1, 2, 3)]
SUNDAY = datetime.fromisoformat('2026-11-08T05:00:00+08:00')
MONTH = datetime.fromisoformat('2026-11-24T05:00:00+08:00')


@pytest.fixture
def env(tmp_path, monkeypatch):
    clock = [datetime.fromisoformat('2026-11-07T17:00:00+08:00')]
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0] if tz is None else clock[0].astimezone(tz)
    monkeypatch.setattr(scheduler, 'datetime', FixedDatetime)
    monkeypatch.setattr(queue_module, 'datetime', FixedDatetime)
    monkeypatch.setattr(deferred_task_store, '_clock', lambda: clock[0].timestamp())
    monkeypatch.setenv('MR3A_RUN_ONCE', '0')
    monkeypatch.setattr(scheduler, 'request_tui_exit', Mock())
    monkeypatch.setattr('custom.action.staged_workflow.pause_workflow', lambda *_: False)
    store = PersistentTaskStateStore(tmp_path / 'state.json', now_factory=lambda: clock[0])
    monkeypatch.setattr(scheduler, 'persistent_task_state_store', store)
    queue.finish()
    deferred_task_store.clear()
    class Tasker:
        stopping = False
        def __init__(self): self.posts = []
        def post_task(self, entry, override):
            self.posts.append((entry, override))
            return SimpleNamespace(job_id=1000 + len(self.posts))
    tasker = Tasker()
    context = SimpleNamespace(tasker=tasker, get_node_data=lambda _: {}, override_pipeline=Mock(return_value=True))
    yield SimpleNamespace(clock=clock, store=store, context=context, tasker=tasker)
    queue.finish()
    deferred_task_store.clear()


def bootstrap(env, entry, override):
    result = scheduler.ManagedTaskSchedulerBootstrap().run(env.context, SimpleNamespace(
        task_detail=SimpleNamespace(task_id=1), custom_action_param={
            'tasks': [{'name': entry, 'entry': entry, 'pipeline_override': override}]}))
    assert result.success


def stop(env, node='stop'):
    env.context.get_node_data = lambda _: {'action': {'type': 'StopTask'}}
    ManagedTaskStopSink().on_node_action(env.context, NotificationType.Starting,
        SimpleNamespace(task_id=queue.snapshot()[2], name=node))


def selected_override(case):
    option = json.loads((RESOURCE / 'tasks/限时活动.json').read_text())['option']['选择要打的逆袭boss']
    patch = next(c for c in option['cases'] if c['name'] == case)['pipeline_override']
    return {**patch, 'AccountSpecific': {'timeout': 12345}}


def retain_loaded_weekly(env):
    node = json.loads((RESOURCE / 'pipeline/每周逆袭悬赏.json').read_text())['每周逆袭悬赏完成回到了主页面']
    assert node['next'] == ['每周逆袭悬赏完成停止任务']
    assert node['action']['param']['custom_action'] == 'RetainManagedTaskUntilStateChange'
    return scheduler.RetainManagedTaskUntilStateChange().run(env.context, SimpleNamespace(
        task_detail=SimpleNamespace(task_id=queue.snapshot()[2]),
        custom_action_param=node['action']['param']['custom_action_param']))


@pytest.mark.parametrize('case', ['逆袭A和逆袭S', '仅逆袭A', '仅逆袭S'])
def test_already_completed_weekly_survives_sunday_without_restart(env, case):
    for gate, due in zip(GATES, [SUNDAY, SUNDAY, MONTH]):
        env.store.set_node(ENTRY, gate, enabled=False, valid_until=due)
    original = selected_override(case)
    bootstrap(env, ENTRY, original)
    before = env.store.path.read_bytes()
    assert retain_loaded_weekly(env).success
    assert env.store.path.read_bytes() == before  # 不能把已有期限顺延一周
    stop(env)
    assert env.tasker.posts[-1][0] == 'AgentSchedulerWait'
    assert queue.seconds_until_runnable() == (SUNDAY - env.clock[0]).total_seconds()
    env.clock[0] = SUNDAY - timedelta(seconds=1)
    scheduler._refresh_persistent_candidate_states()
    assert queue.pop_pending() is None
    env.clock[0] = SUNDAY
    assert scheduler.dispatch_next(env.tasker)
    task = queue.current()
    assert task.entry == ENTRY
    assert task.pipeline_override['AccountSpecific'] == original['AccountSpecific']
    assert task.pipeline_override[GATES[0]]['enabled'] is (case != '仅逆袭A')
    assert task.pipeline_override[GATES[1]]['enabled'] is (case != '仅逆袭S')
    assert task.pipeline_override[GATES[2]]['enabled'] is False  # 月期限不受周重置影响


def test_unselected_phase_cannot_make_only_a_wake_early(env):
    env.store.set_node(ENTRY, GATES[0], enabled=False, valid_until=env.clock[0] + timedelta(hours=1))
    env.store.set_node(ENTRY, GATES[1], enabled=False, valid_until=SUNDAY)
    env.store.set_node(ENTRY, GATES[2], enabled=False, valid_until=MONTH)
    bootstrap(env, ENTRY, selected_override('仅逆袭A'))
    assert retain_loaded_weekly(env).success
    retained = queue.release_recurring_current(queue.snapshot()[2])
    assert retained.not_before == SUNDAY


def test_monthly_only_disabled_state_keeps_its_existing_deadline(env):
    env.store.set_node(ENTRY, GATES[2], enabled=False, valid_until=MONTH)
    bootstrap(env, ENTRY, {GATES[0]: {'enabled': False}, GATES[1]: {'enabled': False}})
    assert retain_loaded_weekly(env).success
    retained = queue.release_recurring_current(queue.snapshot()[2])
    assert retained.not_before == MONTH


def test_once_does_not_wait_for_future_weekly_period(env, monkeypatch):
    monkeypatch.setenv('MR3A_RUN_ONCE', '1')
    for gate, due in zip(GATES, [SUNDAY, SUNDAY, MONTH]):
        env.store.set_node(ENTRY, gate, enabled=False, valid_until=due)
    bootstrap(env, ENTRY, selected_override('逆袭A和逆袭S'))
    assert retain_loaded_weekly(env).success
    stop(env)
    assert not queue.snapshot()[0]
    assert all(entry != 'AgentSchedulerWait' for entry, _ in env.tasker.posts)


def test_permanent_disables_do_not_create_future_candidate(env):
    env.store.set_node(ENTRY, GATES[0], enabled=False, valid_until=None)
    bootstrap(env, ENTRY, {})
    assert retain_loaded_weekly(env).success
    assert queue.release_recurring_current(queue.snapshot()[2]) is None


def test_late_completion_cannot_register_new_current_task(env):
    bootstrap(env, ENTRY, {})
    assert not scheduler.RetainManagedTaskUntilStateChange().run(env.context, SimpleNamespace(
        task_detail=SimpleNamespace(task_id=999), custom_action_param={'nodes': GATES})).success


@pytest.mark.parametrize('entry,deadline,wait_node,opens', [
    ('深渊挑战entry', '2026-11-13T05:00:00+08:00', '深渊挑战挂起到八点', '20:00'),
    ('工坊挑战entry', '2026-11-14T05:00:00+08:00', '工坊挑战等待九点', '09:00'),
])
@pytest.mark.parametrize("initially_disabled", [True, False])
def test_task_disabled_at_boot_resumes_weekly_then_waits_until_event_opens(env, entry, deadline, wait_node, opens, initially_disabled):
    due = datetime.fromisoformat(deadline)
    if initially_disabled:
        env.store.set(entry, enabled=False, valid_until=due)
    override = {'AccountSpecific': {'timeout': 6789}}
    bootstrap(env, entry, override)
    if not initially_disabled:
        file = '深渊挑战' if entry.startswith('深渊') else '工坊挑战'
        pipeline = json.loads((RESOURCE / f'pipeline/{file}.json').read_text())
        node = '登记深渊挑战每周完成' if entry.startswith('深渊') else '登记工坊挑战本周结束'
        assert scheduler.SetManagedTaskPersistentState().run(env.context, SimpleNamespace(
            custom_action_param=pipeline[node]['action']['param']['custom_action_param'],
            task_detail=SimpleNamespace(task_id=queue.snapshot()[2]))).success
        assert env.store.snapshot()[entry].valid_until == due
        stop(env)
    assert env.tasker.posts[-1][0] == 'AgentSchedulerWait'
    env.clock[0] = due - timedelta(seconds=1)
    scheduler._refresh_persistent_candidate_states()
    assert queue.pop_pending() is None
    env.clock[0] = due
    assert scheduler.dispatch_next(env.tasker)
    assert queue.current().entry == entry
    assert queue.current().pipeline_override['AccountSpecific'] == override['AccountSpecific']
    file = '深渊挑战' if entry.startswith('深渊') else '工坊挑战'
    pipeline = json.loads((RESOURCE / f'pipeline/{file}.json').read_text())
    param = pipeline[wait_node]['action']['param']['custom_action_param']
    assert param['daily_times'] == [opens]
    assert scheduler.ScheduleDeferredTask().run(env.context, SimpleNamespace(
        custom_action_param=param, task_detail=SimpleNamespace(task_id=queue.snapshot()[2]),
        reco_detail=SimpleNamespace(best_result=None, filtered_results=[]))).success
    stop(env)
    env.clock[0] = due.replace(hour=int(opens[:2])) - timedelta(seconds=1)
    assert not deferred_task_store.claim_ready()
    env.clock[0] += timedelta(seconds=1)
    assert scheduler.dispatch_next(env.tasker)
    assert queue.current().entry == entry
    assert queue.current().pipeline_override['AccountSpecific'] == override['AccountSpecific']


def test_wait_wakes_at_sunday_and_dispatches_weekly_from_stop_sink(env, monkeypatch):
    for gate, due in zip(GATES, [SUNDAY, SUNDAY, MONTH]):
        env.store.set_node(ENTRY, gate, enabled=False, valid_until=due)
    bootstrap(env, ENTRY, selected_override('逆袭A和逆袭S'))
    assert retain_loaded_weekly(env).success
    stop(env)
    def sleep(context, milliseconds):
        assert milliseconds == int((SUNDAY - env.clock[0]).total_seconds() * 1000)
        env.clock[0] = SUNDAY
        return True
    monkeypatch.setattr(scheduler, 'interruptible_sleep', sleep)
    assert scheduler.ManagedTaskSchedulerWait().run(env.context, None).success
    stop(env, 'AgentSchedulerWaitStop')
    assert queue.current().entry == ENTRY
    assert queue.current().pipeline_override[GATES[0]]['enabled'] is True


def test_same_entry_keeps_separate_options_and_deadlines_for_each_instance(env):
    earlier = env.clock[0] + timedelta(hours=1)
    env.store.set_node(ENTRY, GATES[0], enabled=False, valid_until=earlier)
    env.store.set_node(ENTRY, GATES[1], enabled=False, valid_until=SUNDAY)
    env.store.set_node(ENTRY, GATES[2], enabled=False, valid_until=MONTH)
    result = scheduler.ManagedTaskSchedulerBootstrap().run(env.context, SimpleNamespace(
        task_detail=SimpleNamespace(task_id=1), custom_action_param={'tasks': [
            {'name': 'only-A', 'entry': ENTRY, 'pipeline_override': selected_override('仅逆袭A')},
            {'name': 'only-S', 'entry': ENTRY, 'pipeline_override': selected_override('仅逆袭S')},
        ]}))
    assert result.success
    assert retain_loaded_weekly(env).success
    stop(env)
    assert queue.current().name == 'only-S'
    assert retain_loaded_weekly(env).success
    stop(env)
    candidates = queue.snapshot()[1]
    assert {t.name: t.not_before for t in candidates} == {'only-A': SUNDAY, 'only-S': earlier}


def test_finishing_across_reset_keeps_earlier_registered_wakeup(env):
    bootstrap(env, ENTRY, selected_override('逆袭A和逆袭S'))
    task_id = queue.snapshot()[2]
    assert queue.retain_current_until(task_id, SUNDAY)
    env.clock[0] = SUNDAY + timedelta(minutes=5)
    env.store.set_node(ENTRY, GATES[2], enabled=False, valid_until=MONTH)
    assert retain_loaded_weekly(env).success
    retained = queue.release_recurring_current(task_id)
    assert retained.not_before == SUNDAY
    assert scheduler.dispatch_next(env.tasker)
    assert queue.current().pipeline_override[GATES[0]]['enabled'] is True


def test_already_completed_task_crossing_reset_requeues_immediately(env):
    for gate, due in zip(GATES, [SUNDAY, SUNDAY, MONTH]):
        env.store.set_node(ENTRY, gate, enabled=False, valid_until=due)
    env.clock[0] = SUNDAY - timedelta(seconds=5)
    bootstrap(env, ENTRY, selected_override('逆袭A和逆袭S'))
    # 任务导航回主页期间到点；此前没有本会话的完成登记。
    env.clock[0] = SUNDAY + timedelta(seconds=5)
    assert retain_loaded_weekly(env).success
    stop(env)
    assert queue.current().entry == ENTRY
    assert queue.current().pipeline_override[GATES[0]]['enabled'] is True
    assert queue.current().pipeline_override[GATES[1]]['enabled'] is True
    assert queue.current().pipeline_override[GATES[2]]['enabled'] is False
