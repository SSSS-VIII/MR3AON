"""Replay the channel coupon popup header without a device or Agent SDK mode."""

import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case", ["popup", "missing_title", "missing_close"])
def test_coupon_popup_requires_title_and_clicks_close(case):
    # Other tests register Agent callbacks, which switches the SDK library.
    # A fresh process keeps native OCR and TemplateMatch independent of that.
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), case],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["case"] == case
    assert report["hit"] is (case == "popup")
    if case == "popup":
        x, y, width, height = report["box"]
        # The action inherits this box. It must point at the observed X,
        # not the title or a price/button elsewhere in the channel overlay.
        assert 950 <= x < x + width <= 990
        assert 65 <= y < y + height <= 105


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
    rule = pipeline["启动关闭渠道可币券弹窗"]["recognition"]

    # Store only the popup header. Restore its original 1280×720 coordinates
    # on a blank canvas so both production ROIs are exercised unchanged.
    header = np.asarray(Image.open(
        ROOT / "tests/fixtures/channel_popup/coupon_header.png"
    ).convert("RGB"))[:, :, ::-1]
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[35:190, 250:1040] = header
    if case == "missing_title":
        image[60:115, 280:450] = (44, 44, 44)
    elif case == "missing_close":
        image[60:110, 945:995] = (44, 44, 44)

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
        report = {
            "case": case,
            "hit": recognition.hit,
            "box": list(recognition.box) if recognition.box is not None else None,
        }
        del tasker, resource
    print(json.dumps(report))


if __name__ == "__main__":
    _native_replay(sys.argv[1])
