import os
import json
import time
from datetime import datetime
from typing import Iterator, Optional, Tuple

from PIL import Image
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context
from maa.define import (
    AndRecognitionResult,
    OrRecognitionResult,
    RecognitionDetail,
    Rect,
)

from utils import logger
from custom.reco import Count
from custom.pipeline_params import parse_pipeline_json_param


def _run_set_node_enabled(
    context: Context,
    argv: CustomAction.RunArg,
    enabled: bool,
) -> CustomAction.RunResult:
    label = "EnableNode" if enabled else "DisableNode"
    try:
        param = parse_pipeline_json_param(argv.custom_action_param)
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"{label}: 参数解析失败: {e}")
        return CustomAction.RunResult(success=False)

    if not param:
        logger.error(f"{label}: custom_action_param 为空，缺少 node_name")
        return CustomAction.RunResult(success=False)

    node_name = param.get("node_name")
    if not isinstance(node_name, str):
        logger.error(
            f"{label}: node_name 必须为字符串，实际为 {type(node_name).__name__}"
        )
        return CustomAction.RunResult(success=False)

    name = node_name.strip()
    if not name:
        logger.error(f"{label}: node_name 为空或仅空白")
        return CustomAction.RunResult(success=False)

    if not context.override_pipeline({name: {"enabled": enabled}}):
        logger.error(
            f"{label}: override_pipeline 失败 (node={name!r}, enabled={enabled})"
        )
        return CustomAction.RunResult(success=False)

    logger.debug(f"{label}: {name!r} -> enabled={enabled}")
    return CustomAction.RunResult(success=True)


def _box_to_center(box: object) -> Optional[Tuple[int, int]]:
    """将 box 转为中心点坐标；部分路径下 box 为 list / dict 而非 Rect。"""
    if box is None:
        return None
    if isinstance(box, Rect):
        return int(box.x + box.w // 2), int(box.y + box.h // 2)
    if isinstance(box, (list, tuple)):
        if len(box) >= 4:
            x, y, w, h = int(box[0]), int(box[1]), int(box[2]), int(box[3])
            return x + w // 2, y + h // 2
        if len(box) >= 2:
            return int(box[0]), int(box[1])
        return None
    if isinstance(box, dict):
        if all(k in box for k in ("x", "y", "w", "h")):
            x = int(box["x"])
            y = int(box["y"])
            w = int(box["w"])
            h = int(box["h"])
            return x + w // 2, y + h // 2
        if "x" in box and "y" in box:
            return int(box["x"]), int(box["y"])
        return None
    if hasattr(box, "x") and hasattr(box, "y"):
        x, y = int(box.x), int(box.y)  # type: ignore[attr-defined]
        w = int(getattr(box, "w", 0) or 0)
        h = int(getattr(box, "h", 0) or 0)
        if w or h:
            return x + w // 2, y + h // 2
        return x, y
    return None


def _iter_rects_from_filtered_item(
    item: object,
) -> Iterator[object]:
    """从单条 filtered_results 条目中解析出需要点击的 box（Rect / list / 等）。"""
    if isinstance(item, (AndRecognitionResult, OrRecognitionResult)):
        for sub in item.sub_results or []:
            if isinstance(sub, RecognitionDetail):
                if sub.box is not None:
                    yield sub.box
                else:
                    for nested in sub.filtered_results or []:
                        yield from _iter_rects_from_filtered_item(nested)
            else:
                yield from _iter_rects_from_filtered_item(sub)
        return
    box = getattr(item, "box", None)
    if box is not None:
        yield box


@AgentServer.custom_action("DisableNode")
class DisableNode(CustomAction):
    """
    将特定 node 设置为禁用（enabled: false）。

    参数格式:
    {
        "node_name": "结点名称"
    }

    custom_action_param 须为 JSON 字符串或可序列化为对象的 dict。
    node_name 须为非空字符串；解析失败或 override_pipeline 失败时返回 success=False。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        return _run_set_node_enabled(context, argv, False)


@AgentServer.custom_action("EnableNode")
class EnableNode(CustomAction):
    """
    将特定 node 设置为启用（enabled: true）。

    参数格式:
    {
        "node_name": "结点名称"
    }

    custom_action_param 须为 JSON 字符串或可序列化为对象的 dict。
    node_name 须为非空字符串；解析失败或 override_pipeline 失败时返回 success=False。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        return _run_set_node_enabled(context, argv, True)


@AgentServer.custom_action("NodeOverride")
class NodeOverride(CustomAction):
    """
    在 node 中执行 pipeline_override 。

    参数格式:
    {
        "node_name": {"被覆盖参数": "覆盖值",...},
        "node_name1": {"被覆盖参数": "覆盖值",...}
    }

    {
        "fight": {
            "next": [
                "fight_better"
            ]
        },
        "fight_better_delay": {
            "next": ["歼灭者V型 Lv.80delay"]
        }
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        ppover = json.loads(argv.custom_action_param)

        if not ppover:
            logger.warning("No ppover")
            return CustomAction.RunResult(success=True)

        logger.debug(f"NodeOverride: {ppover}")
        context.override_pipeline(ppover)

        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ResetCount")
class ResetCount(CustomAction):
    """
    重置计数器（幂等：目标节点未初始化时视为已为 0）。

    参数格式:
    {
        "node_name": String # 目标计数器节点名称；省略或空则重置全部节点
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        if not argv.custom_action_param:
            Count.reset_count()
            return CustomAction.RunResult(success=True)

        param = json.loads(argv.custom_action_param)
        if not param:
            Count.reset_count()
            return CustomAction.RunResult(success=True)

        node_name = param.get("node_name", None)
        Count.reset_count(node_name)
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ClearMaxHit")
class ClearMaxHit(CustomAction):
    """
    清除节点的 max_hit 计数。

    参数格式:
    {
        "node_name": String  # 目标节点名称
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        try:
            param = (
                json.loads(argv.custom_action_param) if argv.custom_action_param else {}
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"ClearMaxHit: 参数解析失败 {e}")
            return CustomAction.RunResult(success=False)

        node_name = param.get("node_name", None)
        if not node_name:
            logger.error("ClearMaxHit: 缺少 node_name")
            return CustomAction.RunResult(success=False)

        if context.clear_hit_count(node_name):
            logger.debug(f"ClearMaxHit: 已清除 {node_name}")
            return CustomAction.RunResult(success=True)
        else:
            logger.warning(f"ClearMaxHit: 清除失败或无记录 {node_name}")
            return CustomAction.RunResult(success=False)


@AgentServer.custom_action("AddExpected")
class AddExpected(CustomAction):
    """
    给目标节点的expected参数添加值(单个)

    参数格式:
    {
        "node_name": "TargetNode",  // 目标节点名称
        "value": "NewValue",         // 要添加的值
        "delimiter": "|"             // 值之间的分隔符，默认为"|"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        param = json.loads(argv.custom_action_param)
        node_name = param.get("node_name")
        value = param.get("value")
        delimiter = param.get("delimiter", "|")

        if not node_name or not value:
            logger.error("缺少必要参数: node_name 或 value")
            return CustomAction.RunResult(success=False)

        # 获取目标节点的当前配置
        node_data = context.get_node_data(node_name)
        if not node_data:
            logger.error(f"未找到节点: {node_name}")
            return CustomAction.RunResult(success=False)

        # 获取当前的expected值
        current_expected = (
            node_data.get("recognition", {}).get("param", {}).get("expected", "")
        )

        # 解析当前值并添加新值
        if isinstance(current_expected, str):
            current_values = (
                current_expected.split(delimiter) if current_expected else []
            )
        else:
            # 处理列表中的每个元素，检查是否包含分隔符
            current_values = []
            for item in current_expected:
                if delimiter in item:
                    # 如果元素包含分隔符，拆分后添加
                    current_values.extend(item.split(delimiter))
                else:
                    # 否则直接添加
                    current_values.append(item)

        # 确保值不重复
        if value not in current_values:
            current_values.append(value)

        # 构建新的expected值
        if isinstance(current_expected, str):
            new_expected = delimiter.join(current_values)
        else:
            # 保持列表格式
            new_expected = current_values

        # 更新节点配置
        context.override_pipeline(
            {node_name: {"recognition": {"param": {"expected": new_expected}}}}
        )

        logger.debug(
            f"已为节点 {node_name} 添加值: {value}，新的expected: {new_expected}"
        )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("SubExpected")
class SubExpected(CustomAction):
    """
    从目标节点的expected参数中移除值(单个)

    参数格式:
    {
        "node_name": "TargetNode",  // 目标节点名称
        "value": "ValueToRemove",     // 要移除的值
        "delimiter": "|"              // 值之间的分隔符，默认为"|"
    }
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:

        param = json.loads(argv.custom_action_param)
        node_name = param.get("node_name")
        value = param.get("value")
        delimiter = param.get("delimiter", "|")

        if not node_name or not value:
            logger.error("缺少必要参数: node_name 或 value")
            return CustomAction.RunResult(success=False)

        # 获取目标节点的当前配置
        node_data = context.get_node_data(node_name)
        if not node_data:
            logger.error(f"未找到节点: {node_name}")
            return CustomAction.RunResult(success=False)

        # 获取当前的expected值
        current_expected = (
            node_data.get("recognition", {}).get("param", {}).get("expected", "")
        )

        # 解析当前值并移除指定值
        if isinstance(current_expected, str):
            current_values = (
                current_expected.split(delimiter) if current_expected else []
            )
        else:
            # 处理列表中的每个元素，检查是否包含分隔符
            current_values = []
            for item in current_expected:
                if delimiter in item:
                    # 如果元素包含分隔符，拆分后添加
                    current_values.extend(item.split(delimiter))
                else:
                    # 否则直接添加
                    current_values.append(item)

        # 移除指定值
        if value in current_values:
            current_values.remove(value)

        # 构建新的expected值
        if isinstance(current_expected, str):
            new_expected = delimiter.join(current_values)
        else:
            # 保持列表格式
            new_expected = current_values

        # 更新节点配置
        context.override_pipeline(
            {node_name: {"recognition": {"param": {"expected": new_expected}}}}
        )

        logger.debug(
            f"已从节点 {node_name} 移除值: {value}，新的expected: {new_expected}"
        )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ClickFilteredResults")
class ClickFilteredResults(CustomAction):
    """
    依次点击本节点识别结果中 filtered_results（或 all_results）里每一项的包围盒中心。

    适用于 OCR / TemplateMatch 等多结果场景；内置 Click 默认只会用 index 选中的一条，
    本动作对列表内（经框架过滤后的）每条结果各点一次。

    custom_action_param 为 JSON 字符串，可选字段：
        delay_ms: 每次点击后的间隔毫秒，默认 200
        max_clicks: 最多点击次数，0 表示不限制，默认 0
        source: "filtered"（默认）或 "all"，若需要点击未过滤的全量结果可设为 all
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        delay_ms = 200
        max_clicks = 0
        source = "filtered"
        if argv.custom_action_param:
            try:
                param = json.loads(argv.custom_action_param)
                delay_ms = int(param.get("delay_ms", delay_ms))
                max_clicks = int(param.get("max_clicks", max_clicks))
                source = str(param.get("source", source)).lower()
            except Exception as e:
                logger.warning(f"ClickFilteredResults: 参数解析失败，使用默认值 ({e})")

        rd = argv.reco_detail
        if rd is None or not rd.hit:
            logger.warning("ClickFilteredResults: 当前节点未识别命中，跳过点击")
            return CustomAction.RunResult(success=False)

        if source == "all":
            items = list(rd.all_results or [])
        else:
            items = list(rd.filtered_results or [])

        if not items:
            logger.warning("ClickFilteredResults: 结果列表为空")
            return CustomAction.RunResult(success=False)

        ctrl = context.tasker.controller
        clicked = 0
        for entry in items:
            for raw_box in _iter_rects_from_filtered_item(entry):
                if max_clicks and clicked >= max_clicks:
                    break
                center = _box_to_center(raw_box)
                if center is None:
                    continue
                x, y = center
                ctrl.post_click(x, y).wait()
                clicked += 1
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)
            if max_clicks and clicked >= max_clicks:
                break

        if clicked == 0:
            logger.warning("ClickFilteredResults: 未解析到任何可点击的 box")
            return CustomAction.RunResult(success=False)

        logger.debug(f"ClickFilteredResults: 已点击 {clicked} 次 (source={source})")
        return CustomAction.RunResult(success=True)
