import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch

from runtime import InstanceSession
from runtime import diagnostics
from test_named_instances import registry


def test_screenshot_helper_uses_named_output_without_control_lease(registry, monkeypatch):
    session = InstanceSession("small", registry=registry)
    monkeypatch.setattr("sys.argv", ["screenshot", "small", "test"])
    with patch.object(diagnostics, "InstanceSession", return_value=session) as factory, patch.object(session, "ensure_ready"), patch.object(session, "screenshot", return_value=b"png"), patch.object(session, "control", side_effect=AssertionError("截图不应抢占控制权")):
        diagnostics.main()
    factory.assert_called_once_with("small")
    assert (session.spec.work_root / "debug/adb-shots/test.png").read_bytes() == b"png"
    assert not (registry.get().work_root / "debug/adb-shots/test.png").exists()


def test_recorder_keeps_the_selected_instances_control_lease(registry, monkeypatch):
    script = Path(__file__).resolve().parents[1] / "tools/record_3v3_parkour.py"
    spec = importlib.util.spec_from_file_location("instance_recorder", script)
    recorder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recorder)
    session = InstanceSession("small", registry=registry)
    monkeypatch.setattr("sys.argv", ["recorder", "small"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    def record(handle):
        assert handle is session
        assert handle._owns_control
        with patch.object(handle, "_shell") as shell:
            recorder.adb_tap(handle, 200, 620)
            shell.assert_called_once_with("input", "tap", "200", "620")
        return 0
    with patch.object(recorder, "InstanceSession", return_value=session), patch.object(session, "ensure_ready"), patch.object(recorder, "record", side_effect=record):
        assert recorder.main() == 0
    assert not session._owns_control


def test_bound_input_reuses_transport_without_per_click_waydroid_poll(registry):
    session = InstanceSession("small", registry=registry)
    session._serial = "192.168.241.112:5555"
    with patch.object(session, "_address", side_effect=AssertionError("每次按键不应重新拉取 Waydroid 状态")), patch("runtime.instances.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as run:
        session._adb("shell", "input", "tap", "1", "2")
    assert run.call_args.args[0][1:5] == ["-P", "5038", "-s", "192.168.241.112:5555"]
