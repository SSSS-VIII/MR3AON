"""延后任务的登记与运行时分发动作。"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.deferred_tasks import (
    ManagedTask,
    deferred_task_store,
    managed_task_queue,
    pipeline_override_for_entry,
)
from custom.interruptible import interruptible_sleep
from custom.pipeline_params import parse_pipeline_json_param
from utils.logger import logger


_DURATION_PART = re.compile(r"(\d+)\s*(天|小时|时|分钟|分|秒)")
_DURATION_UNITS = {
    "天": 24 * 60 * 60,
    "小时": 60 * 60,
    "时": 60 * 60,
    "分钟": 60,
    "分": 60,
    "秒": 1,
}
_WRAPPER_ENTRY = "AgentSchedulerTaskWrapper"
_SUBTASK_ENTRY = "AgentSchedulerTaskSubtask"
_FINALIZE_ENTRY = "AgentSchedulerTaskFinalize"
_WAIT_ENTRY = "AgentSchedulerWait"


def parse_chinese_duration_seconds(text: str) -> int | None:
    matches = _DURATION_PART.findall(text)
    if not matches:
        return None
    return sum(int(value) * _DURATION_UNITS[unit] for value, unit in matches)


def _recognition_texts(argv: CustomAction.RunArg) -> list[str]:
    results: list[Any] = []
    if argv.reco_detail.best_result is not None:
        results.append(argv.reco_detail.best_result)
    results.extend(argv.reco_detail.filtered_results)

    texts: list[str] = []
    for result in results:
        text = getattr(result, "text", None)
        if isinstance(text, str) and text and text not in texts:
            texts.append(text)
    return texts


def _take_next_task() -> ManagedTask | None:
    """到期任务优先，其次按 MaaPiCli 原顺序取普通任务。"""
    ready = deferred_task_store.claim_ready()
    if ready:
        first, rest = ready[0], ready[1:]
        if rest:
            deferred_task_store.release_ready(rest)
        return ManagedTask(
            name=first.key,
            entry=first.entry,
            pipeline_override=first.pipeline_override,
        )

    return managed_task_queue.pop_pending()


def _normalize_pipeline_override(raw: Any) -> dict[str, Any]:
    """将 MaaPiCli 任务选项产生的 override 数组按顺序深合并。"""
    def merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
        for key, value in patch.items():
            old = target.get(key)
            if isinstance(old, dict) and isinstance(value, dict):
                merge(old, value)
            else:
                target[key] = deepcopy(value)

    if raw is None:
        return {}
    if isinstance(raw, dict):
        return deepcopy(raw)
    if isinstance(raw, list):
        merged: dict[str, Any] = {}
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"pipeline_override[{index}] 非对象")
            merge(merged, item)
        return merged
    raise ValueError("pipeline_override 必须是对象或对象数组")


def _post_managed_task(tasker: Any, task: ManagedTask) -> bool:
    pipeline_override = deepcopy(task.pipeline_override)
    pipeline_override.update(
        {
            _WRAPPER_ENTRY: {
                "recognition": "DirectHit",
                "action": "DoNothing",
                "next": [f"[JumpBack]{_SUBTASK_ENTRY}", _FINALIZE_ENTRY],
            },
            _SUBTASK_ENTRY: {
                "recognition": "DirectHit",
                "action": "DoNothing",
                "max_hit": 1,
                "next": [task.entry],
            },
            _FINALIZE_ENTRY: {
                "recognition": "DirectHit",
                "action": {
                    "type": "Custom",
                    "param": {"custom_action": "ManagedTaskSchedulerFinalize"},
                },
            },
        }
    )
    try:
        job = tasker.post_task(_WRAPPER_ENTRY, pipeline_override)
    except Exception as exc:
        logger.exception(f"Agent 调度提交失败: entry={task.entry!r}: {exc}")
        return False
    if job.job_id <= 0:
        logger.error(f"Agent 调度提交返回无效 task_id: entry={task.entry!r}")
        return False
    managed_task_queue.set_current(job.job_id, task)
    logger.info(
        f"Agent 调度已提交: task_id={job.job_id}, "
        f"name={task.name!r}, entry={task.entry!r}, "
        f"override_nodes={list(task.pipeline_override)!r}"
    )
    return True


def dispatch_next(tasker: Any) -> bool:
    if tasker.stopping:
        managed_task_queue.finish()
        deferred_task_store.clear()
        return False

    task = _take_next_task()
    if task is not None:
        if _post_managed_task(tasker, task):
            return True
        managed_task_queue.prepend_pending(task)
        return False

    delay = deferred_task_store.seconds_until_next()
    if delay is None:
        managed_task_queue.finish()
        logger.info("Agent 管理的任务队列已全部完成")
        return True

    wait_override = {
        _WAIT_ENTRY: {
            "recognition": "DirectHit",
            "action": {
                "type": "Custom",
                "param": {"custom_action": "ManagedTaskSchedulerWait"},
            },
        }
    }
    try:
        job = tasker.post_task(_WAIT_ENTRY, wait_override)
    except Exception as exc:
        logger.exception(f"Agent 调度提交等待任务失败: {exc}")
        return False
    if job.job_id <= 0:
        logger.error("Agent 调度提交等待任务返回无效 task_id")
        return False
    managed_task_queue.set_current(job.job_id, None)
    return True


@AgentServer.custom_action("ScheduleDeferredTask")
class ScheduleDeferredTask(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        del context
        try:
            param = parse_pipeline_json_param(argv.custom_action_param)
        except Exception as exc:
            logger.error(f"ScheduleDeferredTask: 参数解析失败: {exc}")
            return CustomAction.RunResult(success=False)

        key = param.get("key")
        entry = param.get("entry")
        grace_seconds = param.get("grace_seconds", 0)
        pipeline_override = param.get("pipeline_override")
        if not isinstance(key, str) or not key or not isinstance(entry, str) or not entry:
            logger.error("ScheduleDeferredTask: key/entry 必须是非空字符串")
            return CustomAction.RunResult(success=False)
        if not isinstance(grace_seconds, (int, float)) or isinstance(grace_seconds, bool):
            logger.error("ScheduleDeferredTask: grace_seconds 必须是数字")
            return CustomAction.RunResult(success=False)
        if grace_seconds < 0:
            logger.error("ScheduleDeferredTask: grace_seconds 非法")
            return CustomAction.RunResult(success=False)

        override_source = "explicit"
        if pipeline_override is None and param.get("reuse_current_override", True):
            pipeline_override = pipeline_override_for_entry(entry)
            override_source = f"task:{entry}"
        if pipeline_override is None:
            pipeline_override = {}
            override_source = "empty"

        duration_seconds: int | None = None
        matched_text = ""
        for text in _recognition_texts(argv):
            parsed = parse_chinese_duration_seconds(text)
            if parsed is not None:
                duration_seconds = parsed
                matched_text = text
                break
        if duration_seconds is None:
            logger.error("ScheduleDeferredTask: OCR 结果中未找到倒计时")
            return CustomAction.RunResult(success=False)

        delay_seconds = duration_seconds + float(grace_seconds)
        deferred_task_store.arm(
            key=key,
            entry=entry,
            delay_seconds=delay_seconds,
            pipeline_override=pipeline_override,
        )
        due_time = datetime.now() + timedelta(seconds=delay_seconds)
        logger.info(
            f"延后任务已登记: key={key!r}, entry={entry!r}, "
            f"ocr={matched_text!r}, delay={delay_seconds:g}s, "
            f"due={due_time:%Y-%m-%d %H:%M:%S}, "
            f"override_source={override_source!r}, "
            f"override_nodes={list(pipeline_override)!r}"
        )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ManagedTaskSchedulerBootstrap")
class ManagedTaskSchedulerBootstrap(CustomAction):
    """接收任务计划，并在 bootstrap 结束前提交第一项。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        try:
            param = parse_pipeline_json_param(argv.custom_action_param)
        except Exception as exc:
            logger.error(f"ManagedTaskSchedulerBootstrap: 参数解析失败: {exc}")
            return CustomAction.RunResult(success=False)

        raw_tasks = param.get("tasks")
        if not isinstance(raw_tasks, list):
            logger.error("ManagedTaskSchedulerBootstrap: tasks 必须是数组")
            return CustomAction.RunResult(success=False)

        tasks: list[ManagedTask] = []
        for index, raw in enumerate(raw_tasks):
            if not isinstance(raw, dict):
                logger.error(f"ManagedTaskSchedulerBootstrap: tasks[{index}] 非对象")
                return CustomAction.RunResult(success=False)
            name = raw.get("name", "")
            entry = raw.get("entry")
            if not isinstance(name, str) or not isinstance(entry, str) or not entry:
                logger.error(
                    f"ManagedTaskSchedulerBootstrap: tasks[{index}] name/entry 非法"
                )
                return CustomAction.RunResult(success=False)
            try:
                pipeline_override = _normalize_pipeline_override(
                    raw.get("pipeline_override")
                )
            except ValueError as exc:
                logger.error(f"ManagedTaskSchedulerBootstrap: tasks[{index}] {exc}")
                return CustomAction.RunResult(success=False)
            tasks.append(
                ManagedTask(
                    name=name,
                    entry=entry,
                    pipeline_override=pipeline_override,
                )
            )

        managed_task_queue.activate(tasks, argv.task_detail.task_id)
        logger.info(
            f"Agent 已接管任务队列: count={len(tasks)}, "
            f"entries={[task.entry for task in tasks]!r}"
        )
        return CustomAction.RunResult(success=dispatch_next(context.tasker))


@AgentServer.custom_action("ManagedTaskSchedulerFinalize")
class ManagedTaskSchedulerFinalize(CustomAction):
    """当前真实 task 尚未结束时提交下一项。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        current = managed_task_queue.current()
        if current is not None:
            logger.info(
                f"Agent 调度任务完成: task_id={argv.task_detail.task_id}, "
                f"entry={current.entry!r}"
            )
        return CustomAction.RunResult(success=dispatch_next(context.tasker))


@AgentServer.custom_action("ManagedTaskSchedulerYieldCurrent")
class ManagedTaskSchedulerYieldCurrent(CustomAction):
    """将当前业务任务放回队首，由紧随的 StopTask 触发重新调度。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        del context
        task_id = argv.task_detail.task_id
        task = managed_task_queue.requeue_current(task_id)
        if task is None:
            logger.error(
                f"Agent 调度让出失败: task_id={task_id} 没有可恢复的当前任务"
            )
            return CustomAction.RunResult(success=False)

        logger.info(
            f"Agent 调度已挂起当前任务: task_id={task_id}, "
            f"name={task.name!r}, entry={task.entry!r}, 等待重新编排"
        )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ManagedTaskSchedulerWait")
class ManagedTaskSchedulerWait(CustomAction):
    """保持一个真实 Tasker task 运行，计时结束前提交到期项。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        del argv
        delay = deferred_task_store.seconds_until_next()
        if delay is not None and delay > 0:
            logger.info(f"普通任务已执行完，等待延后任务到期: {delay:.1f}s")
            if not interruptible_sleep(context, math.ceil(delay * 1000)):
                managed_task_queue.finish()
                deferred_task_store.clear()
                return CustomAction.RunResult(success=False)
        return CustomAction.RunResult(success=dispatch_next(context.tasker))
