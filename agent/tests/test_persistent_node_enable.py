"""持久化节点禁用须同时覆盖遗留字段 enable。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom.action.deferred_tasks import (
    _apply_persistent_node_overrides,
    _canonicalize_pipeline_enable_fields,
    _normalize_pipeline_override,
)
from custom.deferred_tasks import ManagedTask
from custom.persistent_task_state import persistent_task_state_store


def test_normalize_syncs_legacy_enable_to_enabled():
    merged = _normalize_pipeline_override(
        [
            {},
            {"清理镜界百器体力": {"enable": True}},
            {"镜界百器每日任务": {"enable": False}},
        ]
    )
    assert merged["清理镜界百器体力"] == {"enable": True, "enabled": True}
    assert merged["镜界百器每日任务"] == {"enable": False, "enabled": False}


def test_persistent_node_disable_overwrites_legacy_enable(tmp_path, monkeypatch):
    state_path = tmp_path / "agent_task_state.json"
    monkeypatch.setattr(persistent_task_state_store, "path", state_path)
    persistent_task_state_store._states.clear()
    persistent_task_state_store._node_states.clear()
    persistent_task_state_store._loaded_cycle = datetime.now(
        timezone(timedelta(hours=8))
    ).replace(hour=5, minute=0, second=0, microsecond=0)

    until = datetime.now().astimezone() + timedelta(hours=8)
    persistent_task_state_store.set_node(
        "镜界百器entry",
        "清理镜界百器体力",
        enabled=False,
        valid_until=until,
    )

    task = ManagedTask(
        name="镜界百器",
        entry="镜界百器entry",
        pipeline_override={
            "清理镜界百器体力": {"enable": True},
            "镜界百器识别目标模式": {"expected": ["炼狱"]},
        },
        base_pipeline_override={
            "清理镜界百器体力": {"enable": True},
            "镜界百器识别目标模式": {"expected": ["炼狱"]},
        },
    )
    applied = _apply_persistent_node_overrides(task)
    node = applied.pipeline_override["清理镜界百器体力"]
    assert node["enabled"] is False
    assert node["enable"] is False


def test_canonicalize_prefers_enabled_when_both_disagree():
    patch = {"清理镜界百器体力": {"enable": True, "enabled": False}}
    _canonicalize_pipeline_enable_fields(patch)
    # 有 enabled 时以 enabled 为准并写回 enable
    assert patch["清理镜界百器体力"] == {"enable": False, "enabled": False}
