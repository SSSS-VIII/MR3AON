from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from custom.action.deferred_tasks import (
    ManagedTaskSchedulerBootstrap,
    ScheduleDeferredTask,
    _post_managed_task,
    _take_next_task,
)
from custom.deferred_tasks import (
    deferred_task_store,
    managed_task_queue,
    pipeline_override_for_entry,
)


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
        self.interface = json.loads(INTERFACE.read_text(encoding="utf-8"))
        self.task_plan = _interface_task_plan(self.interface)

    def tearDown(self):
        deferred_task_store.clear()
        managed_task_queue.finish()

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
