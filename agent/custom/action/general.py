import os
import json
import threading
import time
from copy import deepcopy
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
from custom.deferred_tasks import effective_task_entry, pipeline_override_for_entry
from custom.pipeline_params import parse_pipeline_json_param


_recovery_state_lock = threading.Lock()
_remembered_game_package: Optional[str] = None
_home_retry_task_ids: set[int] = set()


def _deep_merge_dict(target: dict, patch: dict) -> None:
    """原地深合并 pipeline override，保留同一节点下未被覆盖的字段。"""
    for key, value in patch.items():
        old = target.get(key)
        if isinstance(old, dict) and isinstance(value, dict):
            _deep_merge_dict(old, value)
        else:
            target[key] = deepcopy(value)


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


def _get_start_app_package(context: Context) -> Optional[str]:
    """读取启动游戏节点在当前任务配置下最终生效的包名。"""
    node_data = context.get_node_data("启动应用")
    if not isinstance(node_data, dict):
        return None

    action = node_data.get("action")
    if not isinstance(action, dict):
        return None

    param = action.get("param")
    if isinstance(param, dict):
        package = param.get("package")
        if isinstance(package, str) and package.strip():
            return package.strip()

    package = action.get("package")
    if isinstance(package, str) and package.strip():
        return package.strip()
    return None


def _remember_game_package(package: str) -> None:
    global _remembered_game_package
    with _recovery_state_lock:
        _remembered_game_package = package


def _get_remembered_game_package() -> Optional[str]:
    with _recovery_state_lock:
        return _remembered_game_package


def _claim_home_retry(task_id: int) -> bool:
    """每个 Maa task 只允许从主页回入口重试一次。"""
    with _recovery_state_lock:
        if task_id in _home_retry_task_ids:
            return False
        _home_retry_task_ids.add(task_id)
        return True


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


@AgentServer.custom_action("RestartGame")
class RestartGame(CustomAction):
    """使用启动任务记录的包名重启，并在独立空栈子任务中完成启动。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        task_id = argv.task_detail.task_id

        entry = effective_task_entry(argv.task_detail.entry)
        if not isinstance(entry, str) or not entry.strip():
            logger.error("RestartGame: 当前 task 没有有效入口")
            return CustomAction.RunResult(success=False)
        entry = entry.strip()
        if entry == "启动游戏entry":
            logger.error(
                f"RestartGame: 当前仍在启动游戏任务，不进入业务任务重启恢复 "
                f"(task_id={task_id})"
            )
            return CustomAction.RunResult(success=False)

        package = _get_remembered_game_package()
        if not package:
            logger.error("RestartGame: 尚未记录实际启动包名，拒绝使用流水线默认值")
            return CustomAction.RunResult(success=False)

        controller = context.tasker.controller
        try:
            stop_job = controller.post_stop_app(package)
            stop_job.wait()
            if not stop_job.succeeded:
                logger.warning(
                    f"RestartGame: StopApp 未成功 (package={package!r})，继续尝试启动"
                )

            start_job = controller.post_start_app(package)
            start_job.wait()
            if not start_job.succeeded:
                logger.error(f"RestartGame: StartApp 失败 (package={package!r})")
                return CustomAction.RunResult(success=False)
        except Exception as exc:
            logger.exception(f"RestartGame: 执行失败 (package={package!r}): {exc}")
            return CustomAction.RunResult(success=False)

        startup_override = pipeline_override_for_entry("启动游戏entry")
        recovery_override = deepcopy(startup_override)
        recovery_stop = "AgentSchedulerRecoveryStop"
        recovery_patch = {
            # RestartGame 已直接启动正确的包；当前业务 task 中的启动应用节点没有
            # 启动职责，必须禁用；服务器与区服 option 则从启动任务完整继承。
            "启动应用": {"enabled": False},
            "记录启动应用包名": {"enabled": False},
            # 恢复启动只给两分钟；顶层仍是业务任务，失败可再次重启。
            "启动流程": {
                "timeout": 120000,
                "on_error": ["重启游戏"],
            },
            # 启动流程内部不断有节点成功时，框架 timeout 会被重置。
            # 总时限不受此影响，恢复启动超时后继续走 RestartGame。
            "启动游戏总超时已到": {
                "action": {
                    "type": "Custom",
                    "param": {
                        "custom_action": "LoopDeadlineArm",
                        "custom_action_param": {
                            "scope": "启动游戏总超时",
                            "duration_ms": 120000,
                        },
                    },
                },
                "next": ["重启游戏"],
            },
            # 启动流程运行在 context.run_task 创建的空 JumpBack 栈中。
            # 确认主页后先挂起外层业务任务，再停止这个启动子任务。
            "启动游戏到了主页面": {
                "action": {
                    "type": "Custom",
                    "param": {
                        "custom_action": "ManagedTaskSchedulerYieldCurrent",
                    },
                },
                "focus": None,
                "next": [recovery_stop],
                "on_error": ["重启游戏"],
            },
            recovery_stop: {
                "recognition": "DirectHit",
                "action": "StopTask",
                "next": [],
                "on_error": ["终止任务队列"],
            },
            # 无论是外层恢复节点还是启动子任务里再次触发的重启，重启动作
            # 返回后都只能停止当前 PipelineTask，不能继续原有 next 或弹出
            # 业务流程遗留的 JumpBack 栈。
            "重启游戏": {
                "next": [recovery_stop],
            },
        }
        _deep_merge_dict(recovery_override, recovery_patch)

        # MaaContextRunTask 会复制当前 Context 的 override / TaskState，但新建
        # PipelineTask，因此拥有独立的空 JumpBack 栈。启动流程即使结束，也
        # 不可能回到 3v3 等业务节点残留的返回栈。
        detail = context.run_task("重启游戏准备启动总超时", recovery_override)
        if detail is None or not detail.status.succeeded:
            logger.error(
                f"RestartGame: 空栈启动子任务失败 "
                f"(task_id={task_id}, entry={entry!r})"
            )
            return CustomAction.RunResult(success=False)

        # 启动子任务中的 ManagedTaskSchedulerYieldCurrent 已把当前业务任务
        # 放回 Agent 队首。外层重启节点返回后立即 StopTask，由 sink 在停止
        # 前重新调度；绝不能再沿 back.json 的启动 next 继续执行。
        if not context.override_pipeline(
            {
                argv.node_name: {"next": [recovery_stop]},
                recovery_stop: recovery_patch[recovery_stop],
            }
        ):
            logger.error(
                f"RestartGame: 配置外层停止节点失败 "
                f"(task_id={task_id}, entry={entry!r})"
            )
            return CustomAction.RunResult(success=False)

        logger.info(
            f"RestartGame: 已重启 {package!r}，已恢复启动选项 "
            f"{list(startup_override)!r}，已在空栈子任务中完成启动并交还 Agent 调度，"
            f"原任务将从 {entry!r} 恢复"
        )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("RememberGamePackage")
class RememberGamePackage(CustomAction):
    """在启动游戏 task 应用 PI option 后记录实际包名。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        entry = effective_task_entry(argv.task_detail.entry)
        if entry != "启动游戏entry":
            logger.error(
                "RememberGamePackage: 只能在启动游戏 task 中记录包名 "
                f"(entry={entry!r})"
            )
            return CustomAction.RunResult(success=False)

        package = _get_start_app_package(context)
        if not package:
            logger.error("RememberGamePackage: 无法读取启动应用的 package")
            return CustomAction.RunResult(success=False)

        _remember_game_package(package)
        logger.info(f"RememberGamePackage: 已记录 {package!r}")
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("RetryCurrentTaskAtHome")
class RetryCurrentTaskAtHome(CustomAction):
    """全局恢复回到主页后，在继承 Context 状态的空栈子任务中重试。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        entry = effective_task_entry(argv.task_detail.entry)
        if not isinstance(entry, str) or not entry.strip():
            logger.error("RetryCurrentTaskAtHome: 当前 task 没有有效入口")
            return CustomAction.RunResult(success=False)

        entry = entry.strip()
        task_id = argv.task_detail.task_id
        if not _claim_home_retry(task_id):
            logger.warning(
                f"RetryCurrentTaskAtHome: task_id={task_id} 已从主页重试过，升级为重启"
            )
            return CustomAction.RunResult(success=False)

        # MaaContextRunTask 会克隆当前 Context：pipeline override 会被复制，
        # TaskState（max_hit 计数和 anchor）及停止标记则与外层共享；同时新的
        # PipelineTask 拥有独立的空 JumpBack 栈。这样可以彻底丢弃错误路径中
        # 遗留的返回栈，又不会把已经执行过的业务分支重新跑一遍。
        wrapper = "AgentHomeRetryWrapper"
        subtask = "AgentHomeRetrySubtask"
        finalize = "AgentHomeRetryFinalize"
        stop = "AgentHomeRetryStop"
        recovery_override = {
            wrapper: {
                "recognition": "DirectHit",
                "action": "DoNothing",
                "next": [f"[JumpBack]{subtask}", finalize],
            },
            subtask: {
                "recognition": "DirectHit",
                "action": "DoNothing",
                "max_hit": 1,
                "next": [entry],
            },
            finalize: {
                "recognition": "DirectHit",
                "action": {
                    "type": "Custom",
                    "param": {"custom_action": "ManagedTaskSchedulerFinalize"},
                },
                "next": [stop],
                "on_error": ["终止任务队列"],
            },
            stop: {
                "recognition": "DirectHit",
                "action": "StopTask",
                "next": [],
                "on_error": ["终止任务队列"],
            },
        }
        detail = context.run_task(wrapper, recovery_override)
        if detail is None or not detail.status.succeeded:
            logger.error(
                f"RetryCurrentTaskAtHome: 空栈子任务执行失败 "
                f"(task_id={task_id}, entry={entry!r})"
            )
            return CustomAction.RunResult(success=False)

        logger.info(
            f"RetryCurrentTaskAtHome: task_id={task_id} 已在继承状态的空栈子任务中 "
            f"完成从入口 {entry!r} 的恢复"
        )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("AbortTasker")
class AbortTasker(CustomAction):
    """最终恢复失败时停止 Tasker，阻止后续任务在错误页面继续运行。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        try:
            # 不能在当前 CustomAction 回调里 wait；停止完成依赖当前回调先返回。
            context.tasker.post_stop()
        except Exception as exc:
            logger.exception(f"AbortTasker: 请求停止任务队列失败: {exc}")
            return CustomAction.RunResult(success=False)

        logger.error(
            f"AbortTasker: 错误恢复已耗尽，停止任务队列 "
            f"(task_id={argv.task_detail.task_id}, "
            f"entry={effective_task_entry(argv.task_detail.entry)!r})"
        )
        return CustomAction.RunResult(success=True)


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
