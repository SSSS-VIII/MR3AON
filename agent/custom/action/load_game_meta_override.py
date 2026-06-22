"""从本地 resource/data/game-meta.json 读取键值对并覆盖流水线节点"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, MutableMapping, Union, cast

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from custom.pipeline_params import parse_pipeline_json_param
from utils.logger import logger

# ==== 工具函数 ====


def _get_by_dotted_path(root: Any, path: str) -> Any:
    if not path or not path.strip():
        return root
    cur: Any = root
    parts = [p for p in path.strip().split(".") if p]
    for part in parts:
        if not isinstance(cur, MutableMapping) or part not in cur:
            raise KeyError(part)
        cur = cur[part]
    return cur


def _default_expected_set_path(merge_path: str) -> str:
    return "expected" if merge_path == "v1" else "recognition.param.expected"


def _parse_set_path(raw: Any, *, default_set: str) -> str:
    if raw is None:
        return default_set
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("set / target 须为非空字符串")
    return raw.strip()


def _normalize_overrides(raw: Any, *, default_set: str) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        out: List[Dict[str, Any]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise TypeError(f"overrides[{i}] 须为对象")
            node = item.get("node")
            jk = item.get("json_key")
            if not isinstance(node, str) or not node.strip():
                raise ValueError(f"overrides[{i}].node 须为非空字符串")
            if not isinstance(jk, str) or not jk.strip():
                raise ValueError(f"overrides[{i}].json_key 须为非空字符串")
            st = _parse_set_path(
                item.get("set", item.get("target")), default_set=default_set
            )
            entry: Dict[str, Any] = {
                "node": node.strip(),
                "json_key": jk.strip(),
                "set": st,
            }
            if "expected_as_list" in item:
                eal = item["expected_as_list"]
                if not isinstance(eal, bool):
                    raise TypeError(f"overrides[{i}].expected_as_list 须为 bool")
                entry["expected_as_list"] = eal
            out.append(entry)
        if not out:
            raise ValueError("overrides 数组不能为空")
        return out
    if isinstance(raw, dict):
        out = []
        for node, spec in raw.items():
            if not isinstance(node, str) or not node.strip():
                raise ValueError("overrides 对象键须为非空节点名")
            if isinstance(spec, str) and spec.strip():
                out.append(
                    {
                        "node": node.strip(),
                        "json_key": spec.strip(),
                        "set": default_set,
                    }
                )
            elif isinstance(spec, dict):
                jk = spec.get("json_key")
                if not isinstance(jk, str) or not jk.strip():
                    raise ValueError(f"节点 {node!r} 的对象值须含非空 json_key 字符串")
                st = _parse_set_path(
                    spec.get("set", spec.get("target")),
                    default_set=default_set,
                )
                entry = {"node": node.strip(), "json_key": jk.strip(), "set": st}
                if "expected_as_list" in spec:
                    eal = spec["expected_as_list"]
                    if not isinstance(eal, bool):
                        raise TypeError(f"节点 {node!r} 的 expected_as_list 须为 bool")
                    entry["expected_as_list"] = eal
                out.append(entry)
            else:
                raise TypeError(
                    f"节点 {node!r} 的值须为字符串（远端键名）或对象 "
                    f'{{ "json_key", "set"? }}'
                )
        if not out:
            raise ValueError("overrides 对象不能为空")
        return out
    raise TypeError("overrides 须为数组或对象")


def _value_to_remote_text(val: Any) -> str:
    if val is None:
        raise ValueError("值为 null")
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float, bool)):
        return str(val)
    raise TypeError(f"不支持的 JSON 值类型: {type(val).__name__}")


def _build_expected_field(text: str, *, as_list: bool) -> Union[str, List[str]]:
    if as_list:
        return [text]
    return text


def _is_recognition_expected_path(set_path: str, merge_path: str) -> bool:
    if merge_path == "v1":
        return set_path == "expected"
    return set_path == "recognition.param.expected"


def _leaf_value_for_override(
    raw_remote: Any,
    *,
    set_path: str,
    merge_path: str,
    item: Mapping[str, Any],
    global_expected_as_list: bool,
) -> Any:
    if _is_recognition_expected_path(set_path, merge_path):
        eal = item.get("expected_as_list")
        use_list = eal if isinstance(eal, bool) else global_expected_as_list
        text = _value_to_remote_text(raw_remote)
        return _build_expected_field(text, as_list=use_list)
    return _value_to_remote_text(raw_remote)


def _subtree_from_dotted_path(dotted: str, leaf: Any) -> Dict[str, Any]:
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        raise ValueError("set 路径不能为空")
    cur: Any = leaf
    for p in reversed(parts):
        cur = {p: cur}
    return cast(Dict[str, Any], cur)


def _deep_merge_dict(dst: MutableMapping[str, Any], src: Mapping[str, Any]) -> None:
    for k, v in src.items():
        if k in dst and isinstance(dst[k], MutableMapping) and isinstance(v, Mapping):
            _deep_merge_dict(cast(MutableMapping[str, Any], dst[k]), v)
        else:
            dst[k] = v


from utils.runtime_paths import get_runtime_paths

_LOCAL_PATH = str(get_runtime_paths().resource_dir / "data" / "game-meta.json")


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
            logger.warning(f"LoadGameMetaOverride: {_LOCAL_PATH} 不存在，跳过覆盖")
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
            logger.error("LoadGameMetaOverride: expected_merge_path 仅支持 v1 / v2")
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
                logger.error(f"LoadGameMetaOverride: 节点 {node!r} set 无效: {e}")
                return CustomAction.RunResult(success=False)

            if node not in patch:
                patch[node] = {}
            if not isinstance(patch[node], dict):
                logger.error(f"LoadGameMetaOverride: 节点 {node!r} 合并冲突")
                return CustomAction.RunResult(success=False)
            _deep_merge_dict(cast(MutableMapping[str, Any], patch[node]), subtree)

        if not context.override_pipeline(patch):
            logger.error("LoadGameMetaOverride: override_pipeline 失败")
            return CustomAction.RunResult(success=False)

        logger.debug(
            f"LoadGameMetaOverride: 已合并 {len(overrides)} 条本地字段到流水线"
        )
        return CustomAction.RunResult(success=True)
