from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.instances import InstanceRegistry, InstanceSession


@pytest.fixture
def registry(tmp_path):
    (tmp_path / "assets/resource/data").mkdir(parents=True)
    (tmp_path / "tools/ci/defaults").mkdir(parents=True)
    (tmp_path / "assets/interface.json").write_text(json.dumps({
        "interface_version": 2,
        "controller": [{"name": "模拟器", "type": "Adb"}],
        "resource": [{"name": "通用", "path": ["./resource"]}],
        "task": [], "import": [],
    }))
    (tmp_path / "tools/ci/defaults/maa_option.json").write_text('{"logging": true}')
    (tmp_path / "assets/resource/data/game-meta.json").write_text('{"key": "seed"}')
    return InstanceRegistry(tmp_path)


def test_name_reuses_identity_and_never_copies_main_credentials(registry):
    main = registry.get()
    main.config_path.parent.mkdir(parents=True)
    original = '{"task": [{"inputs": {"password": "main-only-secret"}}], "custom": true}'
    main.config_path.write_text(original)
    registry.prepare(main)
    assert main.config_path.read_text() == original
    first = registry.get("小号")
    registry.prepare(first)
    first_config = json.loads(first.config_path.read_text())
    assert first_config["task"] == []
    assert "main-only-secret" not in first.config_path.read_text()
    first_config["task"] = [{"name": "own-task", "inputs": {"password": "own-secret"}}]
    first.config_path.write_text(json.dumps(first_config))
    registry.prepare(first)
    assert json.loads(first.config_path.read_text()) == first_config
    assert registry.get("小号") == first
    assert registry.get("另一个").slot != first.slot
    assert not (first.work_root / "MaaPiCli").exists()
    assert not (first.work_root / "resource").exists()


@pytest.mark.parametrize("name", ["", "../main", ".", "a/b", "a b", "x" * 49])
def test_invalid_names_cannot_escape_runtime_root(registry, name):
    with pytest.raises(ValueError):
        registry.get(name)


def test_corrupt_registry_never_reassigns_an_account(registry):
    registry.root.mkdir()
    (registry.root / "registry.json").write_text('{"one":1,"two":1}')
    with pytest.raises(RuntimeError, match="注册表"):
        registry.get("three")




def test_prepare_does_not_import_legacy_rewards_or_change_current_rewards(registry):
    main = registry.get()
    old = registry.project_root / "assets/debug/reward_shots/reward/one.png"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"legacy-image")
    target = main.work_root / "debug/reward_shots"
    current = target / "reward/one.png"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"current-image")
    registration = '{"dirs": ["reward"]}'
    (target / "registry.json").write_text(registration)
    registry.prepare(main)
    registry.prepare(main)
    assert current.read_bytes() == b"current-image"
    assert (target / "registry.json").read_text() == registration
    current.unlink()  # 模拟日常清理，下一次准备不能从旧源复活截图。
    registry.prepare(main)
    assert not current.exists()
    assert old.read_bytes() == b"legacy-image"
    assert not list(target.glob("历史_*"))
    assert not (main.work_root / "debug/reward_shots_archive").exists()
    assert not (main.work_root / "debug/legacy_rewards_migrated.json").exists()


def test_control_lease_and_read_only_handles_share_the_same_name(registry):
    owner = InstanceSession("small", registry=registry)
    other = InstanceSession("small", registry=registry)
    with owner.control():
        with pytest.raises(RuntimeError, match="已有控制者"):
            with other.control():
                pass
        assert other.spec == owner.spec
    with other.control():
        pass


def test_data_and_interfaces_are_private_but_resources_shared(registry, monkeypatch):
    one, two = registry.get("one"), registry.get("two")
    registry.prepare(one)
    registry.prepare(two)
    (one.work_root / "data/game-meta.json").write_text('{"key": "one"}')
    registry.prepare(one)
    assert json.loads((one.work_root / "data/game-meta.json").read_text()) == {"key": "one"}
    assert json.loads((two.work_root / "data/game-meta.json").read_text()) == {"key": "seed"}
    interface = json.loads((one.work_root / "interface.json").read_text())
    assert interface["resource"][0]["path"] == [str(registry.project_root / "assets/resource")]
    assert Path(interface["agent"]["child_args"][-1]).is_absolute()



def test_environment_does_not_inherit_another_instances_target(registry, monkeypatch):
    monkeypatch.setenv("MR3A_ADB_SERIAL", "wrong")
    monkeypatch.setenv("ANDROID_SERIAL", "wrong")
    monkeypatch.setenv("MR3A_TEST_WORK", "/wrong")
    monkeypatch.setenv("MR3A_PICLI_PID", "999")
    env = registry.get("small").environment("correct")
    assert env["MR3A_ADB_SERIAL"] == env["ANDROID_SERIAL"] == "correct"
    assert env["ADB_SERVER_SOCKET"] == "tcp:5038"
    assert "MR3A_TEST_WORK" not in env and "MR3A_PICLI_PID" not in env








def test_input_requires_the_instances_control_lease(registry):
    session = InstanceSession("small", registry=registry)
    with pytest.raises(RuntimeError, match="control"):
        session.tap(1, 2)
    with session.control(), patch.object(session, "_shell") as shell:
        session.tap(1, 2)
        shell.assert_called_once_with("input", "tap", "1", "2")


def test_existing_environment_rejects_a_valid_but_changed_slot(registry):
    spec = registry.get("one")
    registry.prepare(spec)
    (registry.root / "registry.json").write_text('{"one":2}')
    with pytest.raises(RuntimeError, match="身份"):
        registry.get("one")
