"""回放渠道叉号：启动与通用清理共用关闭按钮识别，不依赖广告文案。"""

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case", ["popup", "rebate", "missing_title", "missing_close", "home"])
def test_channel_popup_clicks_close_independently_of_ad_text(case):
    # Other tests register Agent callbacks, which switches the SDK library.
    # A fresh process keeps native OCR and TemplateMatch independent of that.
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), case],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["case"] == case
    assert report["hit"] is (case in {"popup", "rebate", "missing_title"})
    assert report["back_hit"] == report["hit"]
    if report["hit"]:
        x, y, width, height = report["box"]
        # The action inherits this box. It must point at the observed X,
        # not the title or a price/button elsewhere in the channel overlay.
        assert 950 <= x < x + width <= 990
        assert 65 <= y < y + height <= 105


def test_startup_keeps_settings_before_generic_close_and_removes_title_gate():
    startup = json.loads((ROOT/'assets/resource/pipeline/启动游戏.json').read_text())
    branches = startup['启动流程']['next']
    assert '启动关闭渠道可币券弹窗' not in startup
    assert '启动关闭渠道可币券弹窗' not in branches
    assert branches.index('屏蔽所有组队邀请') < branches.index('处理登录活动弹窗')
    assert branches.index('设置页面上滑') < branches.index('处理登录活动弹窗')


def _native_replay(case):
    import tempfile

    import numpy as np
    from PIL import Image
    from maa.define import LoggingLevelEnum
    from maa.library import Library
    from maa.pipeline import JAnd
    from maa.resource import Resource
    from maa.tasker import Tasker

    resource_dir = ROOT / "assets/resource"
    pipeline = json.loads((resource_dir / "pipeline/启动游戏.json").read_text())
    rule = pipeline["处理登录活动弹窗"]["recognition"]

    # Store only the popup header. Restore its original 1280×720 coordinates
    # on a blank canvas so the shared button search uses device coordinates.
    header = np.asarray(Image.open(
        ROOT / ("tests/fixtures/channel_popup/rebate_header.png" if case == "rebate" else "tests/fixtures/channel_popup/coupon_header.png")
    ).convert("RGB"))[:, :, ::-1]
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[35:190, 250:1040] = header
    if case == "missing_title":
        image[60:115, 280:450] = (44, 44, 44)
    elif case == "missing_close":
        image[60:110, 945:995] = (44, 44, 44)

    if case == "home":
        image = np.asarray(Image.open(ROOT / "tests/fixtures/xumi/lobby.png").convert("RGB"))[:, :, ::-1].copy()

    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix="mr3a-channel-popup-") as log_dir:
        Tasker.set_log_dir(log_dir)
        resource = Resource()
        assert resource.post_bundle(str(resource_dir)).wait().succeeded
        tasker = Tasker()
        assert Library.framework().MaaTaskerBindResource(tasker._handle, resource._handle)
        result = tasker.post_recognition(
            rule["type"], JAnd(**rule["param"]), image
        ).wait().get()
        assert result is not None and len(result.nodes) == 1
        recognition = result.nodes[0].recognition
        back = json.loads((resource_dir / "pipeline/back.json").read_text())["处理叉叉弹窗"]["recognition"]
        back_hit = tasker.post_recognition(back["type"], JAnd(**back["param"]), image).wait().get().nodes[0].recognition.hit
        report = {
            "case": case,
            "back_hit": back_hit,
            "hit": recognition.hit,
            "box": list(recognition.box) if recognition.box is not None else None,
        }
        del tasker, resource
    print(json.dumps(report))


if __name__ == "__main__":
    _native_replay(sys.argv[1])
