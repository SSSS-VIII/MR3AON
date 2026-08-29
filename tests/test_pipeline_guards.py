from __future__ import annotations

import json
import unittest
from pathlib import Path


RESOURCE = Path(__file__).parents[1] / "assets" / "resource"


class PipelineGuardTest(unittest.TestCase):
    def test_daily_completion_registration_is_only_on_explicit_success_paths(self):
        expected = {
            ("3v3.json", "登记3v3每日完成"): ("3v3entry", None),
            ("免费召唤.json", "免费召唤回到主页面"): ("免费召唤entry", None),
            ("忍村试炼.json", "登记忍村试炼每日完成"): ("忍村试炼entry", None),
            ("每日商店.json", "每日商店回到了主页面"): ("每日商店entry", None),
            ("每日悬赏.json", "每日悬赏完成回到了主页面"): ("每日悬赏entry", None),
            ("竞技场.json", "每周跑酷和每日老板娘问答结束"): ("竞技场entry", None),
            ("藏宝图.json", "每日藏宝图完成回到了主页面"): ("每日藏宝图entry", None),
            ("通灵巡逻.json", "登记通灵巡逻每日完成"): ("通灵巡逻entry", None),
            ("家族祈福.json", "登记领取奖励_家族祈福每日完成"): ("领取奖励entry", "领取奖励_家族祈福"),
            ("忍阶任务.json", "登记领取奖励_忍阶任务每日完成"): ("领取奖励entry", "领取奖励_忍阶任务"),
            ("每周兑换码.json", "登记领取奖励_每周兑换码每周完成"): ("领取奖励entry", "领取奖励_每周兑换码"),
            ("活动奖励.json", "登记领取奖励_活动奖励每日完成"): ("领取奖励entry", "领取奖励_活动奖励"),
            ("神龙契约.json", "登记领取奖励_神龙契约每日完成"): ("领取奖励entry", "领取奖励_神龙契约"),
            ("领取战令.json", "登记领取奖励_领取战令每日完成"): ("领取奖励entry", "领取奖励_领取战令"),
        }
        for (filename, node_name), (entry, child_node) in expected.items():
            with self.subTest(filename=filename, node=node_name):
                pipeline = json.loads(
                    (RESOURCE / "pipeline" / filename).read_text(encoding="utf-8")
                )
                param = pipeline[node_name]["action"]["param"]
                self.assertEqual(param["custom_action"], "SetManagedTaskPersistentState")
                state = param["custom_action_param"]
                self.assertEqual(state["entry"], entry)
                self.assertEqual(state.get("node"), child_node)
                self.assertFalse(state["enabled"])
                if node_name == "登记领取奖励_每周兑换码每周完成":
                    self.assertEqual(state["valid_until"], "next_weekly_reset")
                    self.assertEqual(state["weekday"], 2)
                else:
                    self.assertEqual(state["valid_until"], "next_daily_reset")

        deferred_paths = {
            ("3v3.json", "没有匹配模式说明时间不符合"),
            ("小屋修炼.json", "忍者小屋还在修炼"),
            ("忍村试炼.json", "挂起忍村试炼四小时"),
            ("通灵巡逻.json", "登记通灵巡逻预计倒计时"),
            ("藏宝图.json", "藏宝图检查让出调度信号"),
            ("领取饭团.json", "领取饭团回到了主页面"),
            ("小屋修炼.json", "确定继续修炼"),
            ("好友忍币.json", "好友忍币任务完成"),
            ("领取邮件.json", "领取邮件任务完成"),
        }
        for filename, node_name in deferred_paths:
            with self.subTest(deferred=filename, node=node_name):
                pipeline = json.loads(
                    (RESOURCE / "pipeline" / filename).read_text(encoding="utf-8")
                )
                action = pipeline[node_name]["action"]
                self.assertNotEqual(
                    action.get("param", {}).get("custom_action"),
                    "SetManagedTaskPersistentState",
                )

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

    def test_treasure_map_yields_only_from_safe_page_nodes(self):
        pipeline = json.loads(
            (RESOURCE / "pipeline" / "藏宝图.json").read_text(encoding="utf-8")
        )
        signal_node = "藏宝图检查让出调度信号"

        self.assertEqual(
            pipeline[signal_node]["recognition"]["param"]["custom_recognition"],
            "ManagedTaskYieldRequested",
        )
        self.assertEqual(
            pipeline[signal_node]["action"]["param"]["custom_action"],
            "ManagedTaskSchedulerYieldCurrent",
        )
        for safe_node in (
            "藏宝图主页或寻宝助力页面",
            "藏宝图仍在寻宝助力页面",
            "藏宝图点击刷新",
            "藏宝图进入战斗后回到藏宝图页面",
        ):
            with self.subTest(safe_node=safe_node):
                self.assertIn(signal_node, pipeline[safe_node]["next"])

        self.assertEqual(
            pipeline["藏宝图让出调度已回到主页"]["action"]["type"],
            "StopTask",
        )


if __name__ == "__main__":
    unittest.main()
