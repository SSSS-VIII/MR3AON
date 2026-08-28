"""Agent 管理任务的一次性安全让出信号。"""

from __future__ import annotations

from typing import Optional, Union

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType

from custom.deferred_tasks import (
    managed_task_queue,
    managed_task_yield_signal_store,
)


@AgentServer.custom_recognition("ManagedTaskYieldRequested")
class ManagedTaskYieldRequested(CustomRecognition):
    """在安全节点消费 Agent 发出的让出请求；每次请求只命中一次。"""

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        del context
        task_id = argv.task_detail.task_id
        if not managed_task_queue.active_for(task_id):
            return None
        if not managed_task_yield_signal_store.consume(task_id):
            return None
        return CustomRecognition.AnalyzeResult(
            box=[0, 0, 1, 1],
            detail={"task_id": task_id, "yield_requested": True},
        )
