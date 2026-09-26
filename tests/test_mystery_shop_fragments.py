from __future__ import annotations

import re
import unittest
from types import SimpleNamespace

from custom.action.mystery_shop_fragments import (
    CONFIG_NODE,
    FRAGMENT_NODE,
    FRAGMENT_ROSTER,
    ApplyMysteryShopFragmentConfig,
    fragment_pattern,
)


class _Context:
    def __init__(self, attach: dict | None):
        self.node = {"attach": attach} if attach is not None else None
        self.overrides: list[dict] = []
        self.override_ok = True

    def get_node_data(self, name: str):
        self.assert_name = name
        return self.node

    def override_pipeline(self, value: dict):
        self.overrides.append(value)
        return self.override_ok


def _argv():
    return SimpleNamespace(custom_action_param="")


class MysteryShopFragmentConfigTest(unittest.TestCase):
    def test_roster_names_match_shop_cards_after_spaces_are_removed(self):
        card = "剑心 · 卫鲤碎片".replace(" ", "").replace("　", "")
        self.assertRegex(card, fragment_pattern("剑心·卫鲤"))
        self.assertEqual(len(FRAGMENT_ROSTER), len(set(FRAGMENT_ROSTER)))
        for name in FRAGMENT_ROSTER:
            self.assertIn("·", name)
            self.assertRegex(f"{name}碎片", fragment_pattern(name))

    def test_no_selection_leaves_fragment_nodes_disabled(self):
        context = _Context({})
        result = ApplyMysteryShopFragmentConfig().run(context, _argv())
        self.assertTrue(result.success)
        self.assertEqual(context.assert_name, CONFIG_NODE)
        self.assertEqual(context.overrides, [])

    def test_selected_full_names_are_written_to_eighth_slot_only(self):
        context = _Context({"剑心·卫鲤": True, "双焰·小椒": False, "极刃·血影": True})
        result = ApplyMysteryShopFragmentConfig().run(context, _argv())
        self.assertTrue(result.success)
        self.assertEqual(len(context.overrides), 1)
        override = context.overrides[0]
        expected = [
            fragment_pattern("剑心·卫鲤"),
            fragment_pattern("极刃·血影"),
        ]
        self.assertEqual(set(override), {FRAGMENT_NODE})
        node = override[FRAGMENT_NODE]
        self.assertTrue(node["enabled"])
        self.assertEqual(node["recognition"]["param"]["expected"], expected)
        for pattern in node["recognition"]["param"]["expected"]:
            self.assertIsNotNone(
                re.fullmatch(pattern, "剑心·卫鲤碎片")
                or re.fullmatch(pattern, "极刃·血影碎片")
            )

    def test_unknown_attach_key_is_not_purchased(self):
        context = _Context({"白·小黑": True})
        result = ApplyMysteryShopFragmentConfig().run(context, _argv())
        self.assertTrue(result.success)
        self.assertEqual(context.overrides, [])


if __name__ == "__main__":
    unittest.main()
