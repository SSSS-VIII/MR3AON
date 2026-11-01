from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

from runtime.instances import InstanceSession
from utils.adb_device import adb_target
from utils.runtime_paths import build_runtime_paths
from test_named_instances import registry

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_paths_share_resources_and_isolate_mutable_data(registry, monkeypatch):
    spec = registry.get("one")
    monkeypatch.setenv("MR3A_WORK_ROOT", str(spec.work_root))
    paths = build_runtime_paths(project_root=registry.project_root)
    assert paths.debug_dir == spec.work_root / "debug"
    assert paths.data_dir == spec.work_root / "data"
    assert paths.resource_dir == registry.project_root / "assets/resource"


def test_tui_exit_only_targets_bound_picli(monkeypatch):
    from tui.run import find_maa_picli_pids
    monkeypatch.setenv("MR3A_INSTANCE_NAME", "one")
    monkeypatch.setenv("MR3A_WORK_ROOT", "/one")
    monkeypatch.setenv("MR3A_PICLI_PID", "123")
    with patch("pathlib.Path.read_bytes", return_value=b"MR3A_WORK_ROOT=/one\0"), patch("tui.run._is_maa_picli", return_value=True):
        assert find_maa_picli_pids() == [123]
    with patch("pathlib.Path.read_bytes", return_value=b"MR3A_WORK_ROOT=/two\0"):
        assert find_maa_picli_pids() == []


def test_missing_bound_device_never_falls_back_to_other_account(monkeypatch):
    monkeypatch.setenv("MR3A_ADB_SERIAL", "target")
    with patch("utils.adb_device.list_adb_states", return_value=("adb", [("other", "device")])):
        with pytest.raises(RuntimeError, match="绑定"):
            adb_target()
    with patch("utils.adb_device.list_adb_states", return_value=("adb", [("other", "device"), ("target", "device")])):
        assert adb_target() == ("adb", "target")


def test_agent_outputs_and_qa_writes_follow_work_root_in_subprocess(registry):
    spec = registry.get("small")
    registry.prepare(spec)
    (spec.work_root / "data/老板娘问答.json").write_text('[{"问题":"题目","答案":"答案"}]')
    env = spec.environment("target")
    env["PYTHONPATH"] = str(ROOT / "agent")
    code = '''
from pathlib import Path
from custom.persistent_task_state import _agent_task_state_path
from custom.reward_shots import reward_shots_root
from custom.action.download_game_meta import _DATA_DIR
from custom.action.load_game_meta_override import _LOCAL_PATH
from utils.text_match import _resolve_db_path
from utils.runtime_paths import get_runtime_paths
p=get_runtime_paths()
assert _agent_task_state_path()==p.config_dir/'agent_task_state.json'
assert reward_shots_root()==p.debug_dir/'reward_shots'
assert _DATA_DIR==p.data_dir
assert Path(_LOCAL_PATH)==p.data_dir/'game-meta.json'
assert _resolve_db_path('resource/data/老板娘问答.json')==p.data_dir/'老板娘问答.json'
'''
    result = subprocess.run([str(ROOT / ".venv/bin/python"), "-c", code], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    assert list((spec.work_root / "debug/custom").glob("*.log"))


def test_real_picli_uses_directory_flags_without_copying_binary(tmp_path):
    binary = ROOT / "deps/bin/MaaPiCli"
    if not binary.exists():
        pytest.skip("需要本地定制 MaaPiCli")
    support = subprocess.run([str(binary), "--help"], capture_output=True, text=True, check=True)
    if "--user-dir" not in support.stdout:
        pytest.skip("本地 MaaPiCli 尚未重编")
    fixture = ROOT / "tests/fixtures/scheduler_override/interface.json"
    interface = json.loads(fixture.read_text())
    (tmp_path / "interface.json").write_text(json.dumps(interface))
    (tmp_path / "config").mkdir()
    config = {"controller": {"name": "调度测试ADB"}, "resource": "调度测试资源", "adb": {
        "name": "test", "adb_path": "/usr/bin/adb", "address": "127.0.0.1:1",
    }, "task": []}
    # Use the fixture's actual labels; no controller connection is attempted.
    config["controller"]["name"] = interface["controller"][0]["name"]
    config["resource"] = interface["resource"][0]["name"]
    path = tmp_path / "config/maa_pi_config.json"
    path.write_text(json.dumps(config))
    before = path.read_bytes()
    result = subprocess.run([
        str(binary), "--user-dir", str(tmp_path), "--resource-dir", str(tmp_path),
        "--task", "不存在的任务",
    ], capture_output=True, timeout=15)
    assert result.returncode == 2
    assert path.read_bytes() == before
    assert (tmp_path / "config/maa_option.json").is_file()
    assert not (tmp_path / "MaaPiCli").exists()
