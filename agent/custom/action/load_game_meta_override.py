"""从本地 resource/data/game-meta.json 读取键值对并覆盖流水线节点"""

from __future__ import annotations

import json
from typing import Any, Dict, MutableMapping, cast

from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from custom.pipeline_params import parse_pipeline_json_param
from utils.logger import logger
from .remote_json_override_expected import (
    _normalize_overrides,
    _get_by_dotted_path,
    _default_expected_set_path,
    _leaf_value_for_override,
    _subtree_from_dotted_path,
    _deep_merge_dict,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_PATH = str(_PROJECT_ROOT / "assets" / "resource" / "data" / "game-meta.json")


@AgentServer.custom_action("LoadGameMetaOverride")
class LoadGameMetaOverride(CustomAction):
    """从本地 resource/data/game-meta.json 取值，覆盖流水线节点字段。

    overrides 参数格式与 RemoteJsonOverrideExpected 完全一致：
    - 对象简写: {"节点名": "json键名"}
    - 数组完整: [{"node": "节点名", "json_key": "键名", "set": "写入路径"}]

    本地文件不存在时不报错，静默跳过。
    """

    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        try:
            param = parse_pipeline_json_param(argv.custom_action_param)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"LoadGameMetaOverride: 参数解析失败: {e}")
            return CustomAction.RunResult(success=False)

        # 读取本地缓存
        try:
            with open(_LOCAL_PATH, "r", encoding="utf-8") as f:
                data: Any = json.load(f)
        except FileNotFoundError:
            logger.warning(
                f"LoadGameMetaOverride: {_LOCAL_PATH} 不存在，跳过覆盖"
            )
            return CustomAction.RunResult(success=True)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"LoadGameMetaOverride: 读取 {_LOCAL_PATH} 失败: {e}")
            return CustomAction.RunResult(success=True)

        if not isinstance(data, dict):
            logger.error("LoadGameMetaOverride: 本地文件顶层不是 JSON 对象")
            return CustomAction.RunResult(success=True)

        # 可选 root_json_path
        root_path = param.get("root_json_path")
        if isinstance(root_path, str) and root_path.strip():
            try:
                data = _get_by_dotted_path(data, root_path.strip())
            except KeyError as e:
                logger.error(f"LoadGameMetaOverride: root_json_path 缺少键: {e}")
                return CustomAction.RunResult(success=False)
            if not isinstance(data, dict):
                logger.error("LoadGameMetaOverride: root_json_path 指向非对象")
                return CustomAction.RunResult(success=True)

        # 解析 override 规则
        merge_path = str(param.get("expected_merge_path", "v2")).lower()
        if merge_path not in ("v1", "v2"):
            logger.error(
                "LoadGameMetaOverride: expected_merge_path 仅支持 v1 / v2"
            )
            return CustomAction.RunResult(success=False)

        default_set = _default_expected_set_path(merge_path)

        overrides_raw = param.get("overrides")
        if overrides_raw is None:
            logger.error("LoadGameMetaOverride: 缺少 overrides 参数")
            return CustomAction.RunResult(success=False)

        try:
            overrides = _normalize_overrides(overrides_raw, default_set=default_set)
        except (TypeError, ValueError) as e:
            logger.error(f"LoadGameMetaOverride: overrides 无效: {e}")
            return CustomAction.RunResult(success=False)

        expected_as_list = param.get("expected_as_list", True)
        if not isinstance(expected_as_list, bool):
            expected_as_list = True

        # 构建 patch 并覆盖
        patch: Dict[str, Any] = {}

        for item in overrides:
            node = item["node"]
            jk = item["json_key"]
            set_path = item["set"]

            try:
                remote_val = data[jk]
            except KeyError:
                logger.error(
                    f"LoadGameMetaOverride: 本地 JSON 缺少键 {jk!r}"
                    f"（节点 {node!r}）"
                )
                return CustomAction.RunResult(success=False)

            try:
                leaf = _leaf_value_for_override(
                    remote_val,
                    set_path=set_path,
                    merge_path=merge_path,
                    item=item,
                    global_expected_as_list=expected_as_list,
                )
            except (TypeError, ValueError) as e:
                logger.error(
                    f"LoadGameMetaOverride: 键 {jk!r} 取值无效"
                    f"（节点 {node!r}）: {e}"
                )
                return CustomAction.RunResult(success=False)

            try:
                subtree = _subtree_from_dotted_path(set_path, leaf)
            except ValueError as e:
                logger.error(
                    f"LoadGameMetaOverride: 节点 {node!r} set 无效: {e}"
                )
                return CustomAction.RunResult(success=False)

            if node not in patch:
                patch[node] = {}
            if not isinstance(patch[node], dict):
                logger.error(
                    f"LoadGameMetaOverride: 节点 {node!r} 合并冲突"
                )
                return CustomAction.RunResult(success=False)
            _deep_merge_dict(cast(MutableMapping[str, Any], patch[node]), subtree)

        if not context.override_pipeline(patch):
            logger.error("LoadGameMetaOverride: override_pipeline 失败")
            return CustomAction.RunResult(success=False)

        logger.debug(
            f"LoadGameMetaOverride: 已合并 {len(overrides)} 条本地字段到流水线"
        )
        return CustomAction.RunResult(success=True)
