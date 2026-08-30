from __future__ import annotations

import unittest
from types import SimpleNamespace

from custom.action import general
from custom.deferred_tasks import ManagedTask, managed_task_queue


class _Job:
    def __init__(self, succeeded: bool = True):
        self.succeeded = succeeded
        self.wait_called = False

    def wait(self):
        self.wait_called = True
        return self


class _Controller:
    def __init__(self, start_succeeded: bool = True):
        self.start_succeeded = start_succeeded
        self.stopped: list[str] = []
        self.started: list[str] = []

    def post_stop_app(self, package: str):
        self.stopped.append(package)
        return _Job()

    def post_start_app(self, package: str):
        self.started.append(package)
        return _Job(self.start_succeeded)


class _Tasker:
    def __init__(self, controller: _Controller | None = None):
        self.controller = controller or _Controller()
        self.stop_requests = 0

    def post_stop(self):
        self.stop_requests += 1
        return _Job()


class _Context:
    def __init__(self, package: str = "com.example.game"):
        self.package = package
        self.tasker = _Tasker()
        self.pipeline_overrides: list[dict] = []
        self.next_overrides: list[tuple[str, list[str]]] = []
        self.run_tasks: list[tuple[str, dict]] = []

    def get_node_data(self, name: str):
        if name != "启动应用":
            return None
        return {
            "action": {
                "type": "StartApp",
                "param": {"package": self.package},
            }
        }

    def override_pipeline(self, value: dict):
        self.pipeline_overrides.append(value)
        return True

    def override_next(self, name: str, value: list[str]):
        self.next_overrides.append((name, value))
        return True

    def run_task(self, entry: str, pipeline_override: dict):
        self.run_tasks.append((entry, pipeline_override))
        return SimpleNamespace(status=SimpleNamespace(succeeded=True))


def _argv(task_id: int, entry: str, node_name: str):
    return SimpleNamespace(
        task_detail=SimpleNamespace(task_id=task_id, entry=entry),
        node_name=node_name,
    )


class ErrorRecoveryTest(unittest.TestCase):
    def setUp(self):
        with general._recovery_state_lock:
            general._remembered_game_package = None
        managed_task_queue.finish()

    @staticmethod
    def _managed(name: str, entry: str, override: dict | None = None):
        value = override or {}
        return ManagedTask(
            name=name,
            entry=entry,
            pipeline_override=value,
            base_pipeline_override=value,
        )

    def test_remember_package_uses_start_task_override(self):
        context = _Context("com.pandadastudio.ninjamustdie3")
        result = general.RememberGamePackage().run(
            context,
            _argv(1, "启动游戏entry", "记录启动应用包名"),
        )
        self.assertTrue(result.success)
        self.assertEqual(
            general._get_remembered_game_package(),
            "com.pandadastudio.ninjamustdie3",
        )

    def test_home_retry_returns_current_task_to_agent_queue(self):
        context = _Context()
        argv = _argv(22, "藏宝图entry", "全局恢复主页面确认")
        current = self._managed("藏宝图", "藏宝图entry", {"节点": {"enabled": True}})
        managed_task_queue.activate([], 1)
        managed_task_queue.set_current(22, current)

        result = general.RetryCurrentTaskAtHome().run(context, argv)

        self.assertTrue(result.success)
        self.assertEqual(context.run_tasks, [])
        active, pending, task_id = managed_task_queue.snapshot()
        self.assertTrue(active)
        self.assertEqual(task_id, 22)
        self.assertEqual([task.entry for task in pending], ["藏宝图entry"])
        self.assertIsNone(managed_task_queue.current())

    def test_restart_uses_remembered_package_and_restores_current_entry(self):
        general._remember_game_package("com.pandadastudio.ninjamustdie3")
        context = _Context("com.pandadastudio.ninjamustdie3.vivo")
        argv = _argv(33, "每日藏宝图entry", "重启游戏")
        startup_override = {"跳过切换区": {"enabled": True}}
        startup = self._managed("启动游戏", "启动游戏entry", startup_override)
        current = self._managed("每日藏宝图", "每日藏宝图entry")
        managed_task_queue.activate([startup], 1)
        self.assertEqual(managed_task_queue.pop_pending(), startup)
        managed_task_queue.set_current(33, current)

        result = general.RestartGame().run(context, argv)

        self.assertTrue(result.success)
        self.assertEqual(
            context.tasker.controller.stopped,
            ["com.pandadastudio.ninjamustdie3"],
        )
        self.assertEqual(context.tasker.controller.started, [])
        self.assertEqual(context.run_tasks, [])
        _, pending, _ = managed_task_queue.snapshot()
        self.assertEqual(
            [task.entry for task in pending],
            ["启动游戏entry", "每日藏宝图entry"],
        )
        self.assertEqual(pending[0].pipeline_override, startup_override)

    def test_restart_cannot_enqueue_same_current_task_twice(self):
        general._remember_game_package("com.pandadastudio.ninjamustdie3")
        context = _Context()
        argv = _argv(44, "每日藏宝图entry", "重启游戏")
        startup = self._managed("启动游戏", "启动游戏entry")
        current = self._managed("每日藏宝图", "每日藏宝图entry")
        managed_task_queue.activate([startup], 1)
        managed_task_queue.pop_pending()
        managed_task_queue.set_current(44, current)

        self.assertTrue(general.RestartGame().run(context, argv).success)
        self.assertFalse(general.RestartGame().run(context, argv).success)
        self.assertEqual(len(context.tasker.controller.stopped), 1)

    def test_restart_is_disabled_during_startup_task(self):
        general._remember_game_package("com.pandadastudio.ninjamustdie3")
        context = _Context()
        argv = _argv(45, "启动游戏entry", "重启游戏")

        self.assertFalse(general.RestartGame().run(context, argv).success)
        self.assertEqual(context.tasker.controller.stopped, [])
        self.assertEqual(context.tasker.controller.started, [])

    def test_abort_tasker_posts_stop_without_waiting(self):
        context = _Context()
        result = general.AbortTasker().run(
            context,
            _argv(55, "每日藏宝图entry", "终止任务队列"),
        )
        self.assertTrue(result.success)
        self.assertEqual(context.tasker.stop_requests, 1)


if __name__ == "__main__":
    unittest.main()
