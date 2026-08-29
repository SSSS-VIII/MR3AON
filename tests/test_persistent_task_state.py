from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from custom.persistent_task_state import (
    PersistentTaskStateStore,
    next_daily_reset,
    next_weekly_reset,
)


class _Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class PersistentTaskStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mr3a-task-state-")
        self.path = Path(self.temp.name) / "agent_task_state.json"
        self.clock = _Clock(datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc))
        self.store = PersistentTaskStateStore(
            self.path,
            now_factory=self.clock,
        )

    def test_start_creates_an_empty_state_file(self):
        self.assertFalse(self.path.exists())

        self.store.start()

        self.assertTrue(self.path.exists())
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")),
            {
                "version": 1,
                "updated_at": self.clock.now.isoformat(),
                "tasks": {},
                "nodes": {},
            },
        )

    def tearDown(self):
        self.store.stop()
        self.temp.cleanup()

    def test_disabled_state_persists_until_expiry(self):
        valid_until = self.clock.now + timedelta(hours=17)
        self.store.set("TaskAEntry", enabled=False, valid_until=valid_until)
        self.assertFalse(self.store.is_enabled("TaskAEntry"))
        self.assertTrue(self.store.is_enabled("TaskBEntry"))

        reloaded = PersistentTaskStateStore(
            self.path,
            now_factory=self.clock,
        )
        self.assertTrue(reloaded.load())
        self.assertFalse(reloaded.is_enabled("TaskAEntry"))

        self.clock.now = valid_until
        self.assertTrue(reloaded.load())
        self.assertTrue(reloaded.is_enabled("TaskAEntry"))
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["tasks"], {})

    def test_daily_refresh_reloads_external_changes_once_cycle_advances(self):
        self.store.start()
        data = {
            "version": 1,
            "updated_at": self.clock.now.isoformat(),
            "tasks": {
                "TaskAEntry": {"enabled": False, "valid_until": None},
            },
        }
        self.path.write_text(json.dumps(data), encoding="utf-8")

        # 同一 05:00 周期内只使用启动时加载的内存状态。
        self.assertTrue(self.store.is_enabled("TaskAEntry"))
        self.clock.now += timedelta(days=1)
        self.store.refresh_if_needed()
        self.assertFalse(self.store.is_enabled("TaskAEntry"))

    def test_node_override_persists_and_expires_independently(self):
        valid_until = self.clock.now + timedelta(hours=1)
        self.store.set_node(
            "领取奖励entry",
            "领取奖励_每周兑换码",
            enabled=False,
            valid_until=valid_until,
        )
        self.assertEqual(
            self.store.node_overrides("领取奖励entry"),
            {"领取奖励_每周兑换码": False},
        )

        self.clock.now = valid_until
        self.assertEqual(self.store.node_overrides("领取奖励entry"), {})
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["nodes"], {})

    def test_task_completed_after_0500_is_recorded_for_the_new_day(self):
        self.clock.now = datetime(2026, 8, 29, 4, 55, tzinfo=timezone.utc)
        old_reset = next_daily_reset(self.clock.now)
        self.store.start()
        self.store.set("OldTaskEntry", enabled=False, valid_until=old_reset)

        # 任务跨过 05:00，并在 05:05 的完成节点登记本次完成。
        self.clock.now = datetime(2026, 8, 29, 5, 5, tzinfo=timezone.utc)
        new_reset = next_daily_reset(self.clock.now)
        self.store.set("CrossResetTaskEntry", enabled=False, valid_until=new_reset)

        # 随后的 Agent 调度安全点执行日切：旧状态清除，新完成状态保留。
        self.store.refresh_if_needed()
        self.assertTrue(self.store.is_enabled("OldTaskEntry"))
        self.assertFalse(self.store.is_enabled("CrossResetTaskEntry"))
        self.assertEqual(
            self.store.snapshot()["CrossResetTaskEntry"].valid_until,
            datetime(2026, 8, 30, 5, 0, tzinfo=timezone.utc),
        )

    def test_reset_helpers_use_0500_boundaries(self):
        now = datetime(2026, 8, 29, 4, 30, tzinfo=timezone.utc)  # 周六
        self.assertEqual(
            next_daily_reset(now),
            datetime(2026, 8, 29, 5, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            next_weekly_reset(now),
            datetime(2026, 8, 31, 5, 0, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
