from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import custom.action.deferred_tasks as scheduler_actions
from custom.action.deferred_tasks import (
    ManagedTaskSchedulerBootstrap,
    ManagedTaskSchedulerWait,
    ManagedTaskSchedulerYieldCurrent,
    ScheduleDeferredTask,
    dispatch_next,
    _post_managed_task,
    _take_next_task,
    next_daily_time,
)
from custom.deferred_tasks import (
    ManagedTaskYieldSignalStore,
    deferred_task_store,
    managed_task_queue,
    pipeline_override_for_entry,
)
from custom.persistent_task_state import PersistentTaskStateStore


ROOT = Path(__file__).parents[1]
INTERFACE = ROOT / "tests" / "fixtures" / "scheduler_override" / "interface.json"
DEFAULT_MAAPICLI = Path("/home/linn/MaaPiCli/build/bin/RelWithDebInfo/MaaPiCli")


class _PostJob:
    def __init__(self, job_id: int):
        self.job_id = job_id


class _Tasker:
    def __init__(self):
        self.stopping = False
        self.posts: list[tuple[str, dict]] = []

    def post_task(self, entry: str, pipeline_override: dict):
        self.posts.append((entry, pipeline_override))
        return _PostJob(10_000 + len(self.posts))


class _FakeTimer:
    created: list["_FakeTimer"] = []

    def __init__(self, delay, callback, args=()):
        self.delay = delay
        self.callback = callback
        self.args = args
        self.daemon = False
        self.cancelled = False
        self.__class__.created.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.callback(*self.args)


def _interface_task_plan(data: dict) -> list[dict]:
    """使用夹具的 default_case 生成 MaaPiCli 传给 bootstrap 的数组形式。"""
    result: list[dict] = []
    options = data["option"]
    for task in data["task"]:
        overrides: list[dict] = []
        if "pipeline_override" in task:
            overrides.append(task["pipeline_override"])
        for option_name in task.get("option", []):
            option = options[option_name]
            selected = option["default_case"]
            case = next(item for item in option["cases"] if item["name"] == selected)
            if "pipeline_override" in case:
                overrides.append(case["pipeline_override"])
        result.append(
            {
                "name": task["name"],
                "entry": task["entry"],
                "pipeline_override": overrides,
            }
        )
    return result


def _bootstrap_argv(task_plan: list[dict]):
    return SimpleNamespace(
        custom_action_param={"tasks": task_plan},
        task_detail=SimpleNamespace(task_id=9000),
    )


def _schedule_argv(entry: str, key: str):
    result = SimpleNamespace(text="0秒")
    return SimpleNamespace(
        custom_action_param={
            "key": key,
            "entry": entry,
            "reuse_current_override": True,
        },
        reco_detail=SimpleNamespace(best_result=result, filtered_results=[]),
    )


class SchedulerOverrideTest(unittest.TestCase):
    def setUp(self):
        deferred_task_store.clear()
        managed_task_queue.finish()
        self._state_temp = tempfile.TemporaryDirectory(
            prefix="mr3a-persistent-state-"
        )
        self._original_state_store = scheduler_actions.persistent_task_state_store
        scheduler_actions.persistent_task_state_store = PersistentTaskStateStore(
            Path(self._state_temp.name) / "agent_task_state.json",
        )
        self.interface = json.loads(INTERFACE.read_text(encoding="utf-8"))
        self.task_plan = _interface_task_plan(self.interface)

    def tearDown(self):
        deferred_task_store.clear()
        managed_task_queue.finish()
        scheduler_actions.persistent_task_state_store.stop()
        scheduler_actions.persistent_task_state_store = self._original_state_store
        self._state_temp.cleanup()

    def _bootstrap(self) -> _Tasker:
        tasker = _Tasker()
        context = SimpleNamespace(tasker=tasker)
        result = ManagedTaskSchedulerBootstrap().run(
            context,
            _bootstrap_argv(self.task_plan),
        )
        self.assertTrue(result.success)
        return tasker

    def test_normal_and_deferred_tasks_keep_their_own_override(self):
        tasker = self._bootstrap()

        first_override = tasker.posts[-1][1]
        self.assertEqual(
            first_override["TaskAConfig"],
            {"enabled": True, "timeout": 111, "rate_limit": 1111},
        )
        self.assertIn("OnlyA", first_override)
        self.assertNotIn("OnlyB", first_override)

        # 当前是 A，但插入的目标是 B；必须取 B 的模板，不能复制 A。
        result = ScheduleDeferredTask().run(None, _schedule_argv("TaskBEntry", "B"))
        self.assertTrue(result.success)
        deferred_b = _take_next_task()
        self.assertIsNotNone(deferred_b)
        assert deferred_b is not None
        self.assertTrue(_post_managed_task(tasker, deferred_b))

        inserted_override = tasker.posts[-1][1]
        self.assertEqual(
            inserted_override["TaskBConfig"],
            {"enabled": True, "timeout": 222, "rate_limit": 2222},
        )
        self.assertIn("OnlyB", inserted_override)
        self.assertNotIn("OnlyA", inserted_override)

    def test_self_deferred_task_reuses_current_instance_override(self):
        tasker = self._bootstrap()
        result = ScheduleDeferredTask().run(
            None,
            _schedule_argv("TaskAEntry", "A-self"),
        )
        self.assertTrue(result.success)
        deferred_a = _take_next_task()
        self.assertIsNotNone(deferred_a)
        assert deferred_a is not None
        self.assertTrue(_post_managed_task(tasker, deferred_a))

        inserted_override = tasker.posts[-1][1]
        self.assertEqual(inserted_override["TaskAConfig"]["rate_limit"], 1111)
        self.assertIn("OnlyA", inserted_override)
        self.assertNotIn("OnlyB", inserted_override)

    def test_persistently_disabled_candidate_is_retained_and_can_resume(self):
        state_store = scheduler_actions.persistent_task_state_store
        state_store.set("TaskAEntry", enabled=False, valid_until=None)

        tasker = self._bootstrap()
        first_override = tasker.posts[-1][1]
        self.assertEqual(
            first_override["AgentSchedulerTaskSubtask"]["next"],
            ["TaskBEntry"],
        )
        _, pending, _ = managed_task_queue.snapshot()
        self.assertIn("TaskAEntry", [task.entry for task in pending])

        state_store.set("TaskAEntry", enabled=True, valid_until=None)
        self.assertTrue(dispatch_next(tasker))
        self.assertTrue(dispatch_next(tasker))
        resumed_override = tasker.posts[-1][1]
        self.assertEqual(
            resumed_override["AgentSchedulerTaskSubtask"]["next"],
            ["TaskAEntry"],
        )

    def test_all_disabled_candidates_enter_wait_instead_of_finishing(self):
        state_store = scheduler_actions.persistent_task_state_store
        for task in self.task_plan:
            state_store.set(task["entry"], enabled=False, valid_until=None)

        tasker = self._bootstrap()
        self.assertEqual(tasker.posts[-1][0], "AgentSchedulerWait")
        _, pending, _ = managed_task_queue.snapshot()
        self.assertEqual(len(pending), len(self.task_plan))

        state_store.set("TaskAEntry", enabled=True, valid_until=None)
        context = SimpleNamespace(tasker=tasker)
        result = ManagedTaskSchedulerWait().run(context, SimpleNamespace())
        self.assertTrue(result.success)
        self.assertEqual(
            tasker.posts[-1][1]["AgentSchedulerTaskSubtask"]["next"],
            ["TaskAEntry"],
        )

    def test_node_override_applies_to_every_duplicate_without_mixing_base_config(self):
        first = self.task_plan[0]
        first["pipeline_override"].append(
            {
                "InstanceConfig": {"value": "first"},
                "SharedRewardNode": {"enabled": True, "source": "first"},
            }
        )
        duplicate = json.loads(json.dumps(first))
        duplicate["name"] = "任务A第二份"
        duplicate["pipeline_override"][-1] = {
            "InstanceConfig": {"value": "second"},
            "SharedRewardNode": {"enabled": True, "source": "second"},
        }
        self.task_plan.append(duplicate)
        scheduler_actions.persistent_task_state_store.set_node(
            "TaskAEntry",
            "SharedRewardNode",
            enabled=False,
            valid_until=None,
        )

        tasker = self._bootstrap()
        first_override = tasker.posts[-1][1]
        self.assertEqual(first_override["InstanceConfig"]["value"], "first")
        self.assertEqual(
            first_override["SharedRewardNode"],
            {"enabled": False, "source": "first"},
        )

        self.assertTrue(dispatch_next(tasker))  # TaskB
        self.assertTrue(dispatch_next(tasker))  # 启动游戏
        self.assertTrue(dispatch_next(tasker))  # 第二份 TaskA
        second_override = tasker.posts[-1][1]
        self.assertEqual(second_override["InstanceConfig"]["value"], "second")
        self.assertEqual(
            second_override["SharedRewardNode"],
            {"enabled": False, "source": "second"},
        )

    def test_startup_override_comes_from_startup_task_template(self):
        self._bootstrap()
        startup = pipeline_override_for_entry("启动游戏entry")
        self.assertEqual(
            startup["StartupConfig"],
            {"enabled": True, "timeout": 333, "rate_limit": 3333},
        )
        self.assertTrue(startup["SkipServerSwitch"]["enabled"])
        self.assertNotIn("OnlyA", startup)
        self.assertNotIn("OnlyB", startup)

    def test_recovery_yield_runs_ready_task_then_resumes_current_task(self):
        tasker = self._bootstrap()

        deferred_task_store.arm(
            key="urgent",
            entry="UrgentEntry",
            delay_seconds=0,
            pipeline_override={"UrgentOnly": {"enabled": True}},
        )
        argv = SimpleNamespace(task_detail=SimpleNamespace(task_id=10_001))
        result = ManagedTaskSchedulerYieldCurrent().run(None, argv)
        self.assertTrue(result.success)

        # StopTask sink 会调用 dispatch_next：先取到期任务。
        self.assertTrue(dispatch_next(tasker))
        urgent_override = tasker.posts[-1][1]
        self.assertEqual(
            urgent_override["AgentSchedulerTaskSubtask"]["next"],
            ["UrgentEntry"],
        )
        self.assertIn("UrgentOnly", urgent_override)

        # 到期任务结束后，原 A 任务从队首带原 override 恢复。
        self.assertTrue(dispatch_next(tasker))
        resumed_override = tasker.posts[-1][1]
        self.assertEqual(
            resumed_override["AgentSchedulerTaskSubtask"]["next"],
            ["TaskAEntry"],
        )
        self.assertIn("OnlyA", resumed_override)
        self.assertNotIn("OnlyB", resumed_override)

    def test_managed_yield_signal_is_consumed_only_once(self):
        _FakeTimer.created.clear()
        store = ManagedTaskYieldSignalStore(timer_factory=_FakeTimer)
        store.arm(101, 3600)

        self.assertFalse(store.consume(101))
        self.assertEqual(_FakeTimer.created[-1].delay, 3600)
        _FakeTimer.created[-1].fire()
        self.assertTrue(store.consume(101))
        self.assertFalse(store.consume(101))

    def test_rearming_yield_signal_invalidates_the_old_timer(self):
        _FakeTimer.created.clear()
        store = ManagedTaskYieldSignalStore(timer_factory=_FakeTimer)
        store.arm(101, 3600)
        old_timer = _FakeTimer.created[-1]
        store.arm(102, 3600)

        self.assertTrue(old_timer.cancelled)
        old_timer.fire()
        self.assertFalse(store.consume(102))
        _FakeTimer.created[-1].fire()
        self.assertTrue(store.consume(102))

    def test_next_daily_time_uses_fixed_points_and_rolls_to_tomorrow(self):
        daily_times = ["13:00", "20:00"]
        cases = (
            (
                datetime(2026, 8, 28, 8, 30),
                datetime(2026, 8, 28, 13, 0),
            ),
            (
                datetime(2026, 8, 28, 13, 0, 1),
                datetime(2026, 8, 28, 20, 0),
            ),
            (
                datetime(2026, 8, 28, 21, 0),
                datetime(2026, 8, 29, 13, 0),
            ),
        )
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(
                    next_daily_time(daily_times, now=now),
                    expected,
                )

    def test_daily_times_schedule_does_not_read_ocr(self):
        argv = SimpleNamespace(
            custom_action_param={
                "key": "fixed-time",
                "entry": "TaskAEntry",
                "daily_times": ["13:00", "20:00"],
                "reuse_current_override": False,
            },
            reco_detail=None,
        )

        result = ScheduleDeferredTask().run(None, argv)

        self.assertTrue(result.success)
        deferred = deferred_task_store.snapshot()
        self.assertEqual(len(deferred), 1)
        self.assertEqual(deferred[0][0].key, "fixed-time")
        self.assertEqual(deferred[0][0].entry, "TaskAEntry")

    def test_fixture_is_accepted_by_real_maapicli_parser(self):
        maapicli = Path(os.environ.get("MAAPICLI_BIN", DEFAULT_MAAPICLI))
        if not maapicli.is_file():
            self.skipTest(f"MaaPiCli 不存在: {maapicli}")

        with tempfile.TemporaryDirectory(prefix="mr3a-scheduler-pi-") as temp:
            run_dir = Path(temp)
            shutil.copy2(maapicli, run_dir / "MaaPiCli")
            shutil.copy2(INTERFACE, run_dir / "interface.json")
            (run_dir / "resource").mkdir()
            config_dir = run_dir / "config"
            config_dir.mkdir()
            config = {
                "controller": {"name": "测试控制器"},
                "adb": {"adb_path": "/usr/bin/adb", "address": "127.0.0.1:1"},
                "resource": "测试资源",
                "task": [
                    {
                        "name": task["name"],
                        "option": [
                            {
                                "name": option_name,
                                "value": self.interface["option"][option_name][
                                    "default_case"
                                ],
                                "values": [],
                                "inputs": {},
                            }
                            for option_name in task.get("option", [])
                        ],
                    }
                    for task in self.interface["task"]
                ],
            }
            (config_dir / "maa_pi_config.json").write_text(
                json.dumps(config, ensure_ascii=False),
                encoding="utf-8",
            )
            for library in maapicli.parent.glob("*.so"):
                os.symlink(library, run_dir / library.name)

            completed = subprocess.run(
                [str(run_dir / "MaaPiCli")],
                input="7\n",
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )

        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 0, output)
        self.assertIn("Agent 调度 override 自测", output)
        self.assertIn("任务A", output)
        self.assertIn("任务B", output)


if __name__ == "__main__":
    unittest.main()
