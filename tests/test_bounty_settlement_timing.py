"""原生 PipelineTask 时序回归：点击后画面暂留时，不能重入结算截图。"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_bounty_confirm_waits_for_result_page_transition():
    # 其它测试会把 SDK 切到 AgentServer 模式，原生回放须在独立进程运行。
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())], cwd=ROOT,
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]


def _native_replay():
    import json
    import tempfile
    import time

    import numpy as np
    from maa.controller import CustomController
    from maa.custom_recognition import CustomRecognition
    from maa.custom_action import CustomAction
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.define import LoggingLevelEnum

    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    Tasker.set_log_dir(tempfile.mkdtemp(prefix="mr3a-settle-native-"))

    class Screen(CustomController):
        """纯内存控制器：点击后按钮继续存在 500ms，再进入列表。"""
        def __init__(self):
            super().__init__()
            self.clicked_at = None
            self.clicks = 0
            self.shots = 0

        def connect(self):
            return True

        def request_uuid(self):
            return "offline-settlement"

        def get_features(self):
            return 0

        def screencap(self):
            return np.zeros((720, 1280, 3), dtype=np.uint8)

        def click(self, x, y):
            self.clicks += 1
            if self.clicked_at is None:
                self.clicked_at = time.monotonic()
            return True

    class Button(CustomRecognition):
        def __init__(self, screen):
            super().__init__()
            self.screen = screen

        def analyze(self, context, argv):
            active = (
                self.screen.clicked_at is None
                or time.monotonic() - self.screen.clicked_at < 0.5
            )
            return CustomRecognition.AnalyzeResult(
                box=[602, 658, 93, 42] if active else None, detail={}
            )

    class Capture(CustomAction):
        def __init__(self, screen):
            super().__init__()
            self.screen = screen

        def run(self, context, argv):
            self.screen.shots += 1
            return CustomAction.RunResult(success=True)

    resource = Resource()
    assert resource.post_bundle(str(ROOT / "assets/resource")).wait().succeeded
    tasker = Tasker()
    results = []
    cases = [
        ("每日悬赏", "每日悬赏"),
        ("S_SS+", "S_SS+悬赏"),
        ("每周逆袭悬赏", "每周逆袭悬赏悬赏"),
        ("每日逆袭悬赏", "每日逆袭悬赏刷出A"),
        ("每日逆袭悬赏", "每日逆袭悬赏悬赏"),
        ("每日逆袭悬赏", "每日逆袭悬赏清A"),
    ]
    # 先证明旧时序能够复现问题，再回放六条实际配置的结算链。
    for filename, prefix, fixed in [(cases[0][0], cases[0][1], False)] + [
        (filename, prefix, True) for filename, prefix in cases
    ]:
        screen = Screen()
        assert screen.post_connection().wait().succeeded
        assert tasker.bind(resource, screen)
        resource.unregister_custom_recognition("ProbeButton")
        resource.unregister_custom_action("ProbeCapture")
        assert resource.register_custom_recognition("ProbeButton", Button(screen))
        assert resource.register_custom_action("ProbeCapture", Capture(screen))
        button = {"type": "Custom", "param": {"custom_recognition": "ProbeButton"}}
        actual = json.loads(
            (ROOT / "assets/resource/pipeline" / (filename + ".json")).read_text(encoding="utf-8")
        )
        shot, click = prefix + "结算截图", prefix + "结算确定"
        leaf = {"recognition": "DirectHit", "pre_delay": 0, "post_delay": 0, "next": []}
        override = {
            "ProbeBattle": {
                **leaf, "next": ["[JumpBack]" + shot, "ProbeReturned"],
            },
            shot: {
                **actual[shot], "recognition": button,
                "action": {"type": "Custom", "param": {"custom_action": "ProbeCapture"}},
                "pre_delay": 200, "post_delay": 200,
                "timeout": 300, "rate_limit": 10, "on_error": ["ProbeRecovery"],
            },
            click: {
                **actual[click], "recognition": button, "pre_delay": 200,
                "post_delay": actual[click]["post_delay"] if fixed else 200,
            },
            "ProbeReturned": leaf,
            "ProbeRecovery": leaf,
        }
        task = tasker.post_task("ProbeBattle", override).wait().get()
        names = [node.name for node in task.nodes]
        assert "ProbeReturned" in names, names
        assert ("ProbeRecovery" in names) == (not fixed), (fixed, names)
        assert screen.clicks == 1, names
        assert screen.shots == (1 if fixed else 2), names
        results.append({"node": click, "fixed": fixed, "recovery": "ProbeRecovery" in names})
    return results


if __name__ == "__main__":
    print(_native_replay())
