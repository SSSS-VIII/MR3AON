"""用主环境实际列表截图回放 OCR，不连接或操作设备。"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WeeklyBountyOCRTest(unittest.TestCase):
    def test_exhausted_s_during_refresh_cooldown(self):
        # 其它 Agent 单测会把 SDK 切到 MaaAgentServer，原生 OCR 要单独进程加载。
        if os.environ.get("MR3A_WEEKLY_OCR_WORKER") != "1":
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve())],
                env={**os.environ, "MR3A_WEEKLY_OCR_WORKER": "1"},
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout[-4000:] + result.stderr[-4000:])
            if "skipped=" in result.stderr:
                self.skipTest(result.stderr.strip())
            return
        try:
            import numpy as np
            from PIL import Image
            from maa.define import LoggingLevelEnum
            from maa.library import Library
            from maa.pipeline import JAnd
            from maa.resource import Resource
            from maa.tasker import Tasker
        except ImportError as exc:
            self.skipTest(f"离线 OCR 需要 MaaFramework、numpy、Pillow: {exc}")

        resource_dir = ROOT / "assets/resource"
        if not (resource_dir / "model/ocr/rec.onnx").exists():
            self.skipTest("未安装项目 OCR 模型")
        pipeline = json.loads(
            (resource_dir / "pipeline/每周逆袭悬赏.json").read_text(encoding="utf-8")
        )
        rule = pipeline["每周逆袭悬赏列表页识别到次数上限_阶段1"]["recognition"]
        # 原图 S=0、A=2、SS+=0，刷新按钮正在倒计时。
        image = np.array(Image.open(
            ROOT / "tests/fixtures/weekly_bounty/list_s_exhausted.png"
        ).convert("RGB"))[:, :, ::-1].copy()
        Tasker.set_stdout_level(LoggingLevelEnum.Error)
        with tempfile.TemporaryDirectory(prefix="mr3a-weekly-ocr-") as log_dir:
            Tasker.set_log_dir(log_dir)
            resource = Resource()
            self.assertTrue(resource.post_bundle(str(resource_dir)).wait().succeeded)
            tasker = Tasker()
            # 显式图像识别无需设备；SDK 的 bind 同时要求控制器，因此只绑定资源。
            self.assertTrue(Library.framework().MaaTaskerBindResource(
                tasker._handle, resource._handle
            ))

            def recognize(param):
                result = tasker.post_recognition(
                    "And", JAnd(**param), image
                ).wait().get()
                self.assertIsNotNone(result)
                self.assertEqual(len(result.nodes), 1)
                return result.nodes[0].recognition.hit

            self.assertTrue(recognize(rule["param"]))
            old = copy.deepcopy(rule["param"])
            old["all_of"][0]["recognition"]["param"] = {
                "roi": [1068, 130, 155, 79], "expected": ["刷新"]
            }
            old["all_of"][1]["recognition"]["param"] = {
                "roi": [570, 50, 360, 50], "expected": ["次数上限"]
            }
            self.assertFalse(recognize(old))
            # A:2 不能替代 S:2，也不能由 SS+:0 命中 S。
            for expected in (r"逆袭S\s*[:：]\s*2(?!\d)", r"逆袭SS\s*[:：]\s*0(?!\d)"):
                other = copy.deepcopy(rule["param"])
                other["all_of"][1]["recognition"]["param"]["expected"] = [expected]
                self.assertFalse(recognize(other))
            del tasker, resource


if __name__ == "__main__":
    unittest.main()
