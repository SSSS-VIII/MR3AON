from __future__ import annotations

import json
import unittest
from pathlib import Path


RESOURCE = Path(__file__).parents[1] / "assets" / "resource"


class PipelineGuardTest(unittest.TestCase):
    def test_default_timeout_and_error_route_are_explicit(self):
        defaults = json.loads(
            (RESOURCE / "default_pipeline.json").read_text(encoding="utf-8")
        )["Default"]

        self.assertEqual(defaults["timeout"], 30_000)
        self.assertEqual(defaults["on_error"], "Default_on_error")

    def test_treasure_fight_waits_for_loading_icon_to_disappear(self):
        pipeline = json.loads(
            (RESOURCE / "pipeline" / "藏宝图.json").read_text(encoding="utf-8")
        )
        shared_fight = json.loads(
            (RESOURCE / "pipeline" / "fight.json").read_text(encoding="utf-8")
        )["fight"]
        expected = {
            "藏宝图调用fight": (
                "藏宝图等待进入战斗图标消失",
                "fight",
            ),
            "清自己藏宝图调用fight": (
                "清自己藏宝图等待进入战斗图标消失",
                "清自己藏宝图fight",
            ),
        }

        for name, (wait_node_name, fight_node_name) in expected.items():
            with self.subTest(name=name):
                self.assertEqual(pipeline[name]["rate_limit"], 2000)
                self.assertEqual(pipeline[name]["next"], [wait_node_name])
                wait_node = pipeline[wait_node_name]
                self.assertTrue(wait_node["inverse"])
                self.assertEqual(
                    wait_node["recognition"]["param"]["template"],
                    ["进入战斗中.png"],
                )
                self.assertEqual(wait_node["next"], [fight_node_name])

        self.assertNotIn("藏宝图降低fight识别速度", pipeline)
        self.assertNotIn("清自己藏宝图降低fight识别速度", pipeline)
        self.assertEqual(shared_fight["rate_limit"], 200)
        self.assertEqual(shared_fight["timeout"], 40_000)


if __name__ == "__main__":
    unittest.main()
