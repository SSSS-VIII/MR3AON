from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ci"))

from update_fragment_roster import (  # noqa: E402
    fragment_checkbox_cases,
    load_roster_file,
    merge_order,
    sync_tasks_cases,
)


class FragmentRosterSyncTest(unittest.TestCase):
    def test_merge_keeps_old_order_and_appends_new(self):
        old = ["A·一", "B·二", "C·三"]
        fetched = ["B·二", "D·四", "A·一", "C·三"]
        self.assertEqual(merge_order(old, fetched), ["A·一", "B·二", "C·三", "D·四"])

    def test_shipped_roster_matches_agent_and_task_cases(self):
        roster_path = ROOT / "assets" / "resource" / "data" / "fragment-roster.json"
        tasks_path = ROOT / "assets" / "resource" / "tasks" / "日常任务.json"
        names = load_roster_file(roster_path)
        self.assertGreaterEqual(len(names), 1)
        self.assertEqual(len(names), len(set(names)))

        from custom.action.mystery_shop_fragments import FRAGMENT_ROSTER

        self.assertEqual(FRAGMENT_ROSTER, names)

        tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        cases = tasks["option"]["勾玉购买忍者碎片"]["cases"]
        self.assertEqual([case["name"] for case in cases], names)
        self.assertEqual(cases, fragment_checkbox_cases(names))

    def test_sync_tasks_is_idempotent(self):
        import tempfile

        tasks_path = ROOT / "assets" / "resource" / "tasks" / "日常任务.json"
        names = load_roster_file(
            ROOT / "assets" / "resource" / "data" / "fragment-roster.json"
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "日常任务.json"
            target.write_text(tasks_path.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertFalse(sync_tasks_cases(target, names))
            self.assertTrue(sync_tasks_cases(target, names + ["测试·角色"]))
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(
                [c["name"] for c in data["option"]["勾玉购买忍者碎片"]["cases"]],
                names + ["测试·角色"],
            )


if __name__ == "__main__":
    unittest.main()
