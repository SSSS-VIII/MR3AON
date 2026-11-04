"""阶段工作流与现有 Agent 队列的成功/暂停交接。"""
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction

from custom import staged_workflow as workflows
from custom.deferred_tasks import managed_task_queue, deferred_task_store, managed_task_yield_signal_store
from custom.pipeline_params import parse_pipeline_json_param
from tui.run import request_tui_exit
from utils.logger import logger


def pause_workflow(task_id: int, reason: str) -> bool:
    if not workflows.stage_is_guarded(task_id):
        return False
    stage = workflows.active_stage(task_id)
    try:
        if stage is not None:
            workflows.stage_store.mark(stage, "paused", reason=reason)
    except Exception as exc:
        # 写盘失败时旧running记录也会阻止下次自动重放。
        logger.error(f"工作流暂停记录失败：{exc}")
    workflows.forget_stage(task_id)
    managed_task_queue.finish()
    deferred_task_store.clear()
    managed_task_yield_signal_store.clear()
    request_tui_exit("staged_workflow_paused")
    logger.error(f"一次性工作流已暂停：{reason}；请核对进度和页面后再恢复")
    return True


@AgentServer.custom_action("BeginWorkflowStage")
class BeginWorkflowStage(CustomAction):
    def run(self, context, argv):
        task_id = argv.task_detail.task_id
        workflows.guard_stage(task_id)
        try:
            param = parse_pipeline_json_param(argv.custom_action_param)
            config_node = context.get_node_data(param["config_node"])
            config = config_node["attach"]
            # 教程与日常/其它账号流程不得在同一个计划里互相插队。
            for entry in managed_task_queue.plan_order():
                data = context.get_node_data(entry) or {}
                if data.get("attach", {}).get("workflow") != param["workflow"]:
                    raise ValueError("一次性工作流须使用独立计划，不能与日常任务混跑")
            stage = workflows.Stage(
                workflow=param["workflow"], account=config["account"].strip(),
                revision=param["revision"], number=param["stage"],
                timing_mode=config.get("timing_mode", "post_click"),
                initial_delay_ms=int(config.get("initial_delay_ms", 0)),
                interval_offset_ms=int(config.get("interval_offset_ms", 0)),
            )
            # 公共back等节点出错也必须暂停，不能进入日常重启恢复链。
            stop = param["failure_node"]
            if not context.override_pipeline({
                "Default_on_error": {"recognition": "DirectHit", "action": "DoNothing", "next": [stop]},
                "全局错误恢复": {"recognition": "DirectHit", "action": "DoNothing", "next": [stop]},
            }):
                raise RuntimeError("设置阶段恢复策略失败")
            if not workflows.stage_store.begin(stage, retry=config.get("retry") is True):
                if not context.override_next(argv.node_name, [param["skip_node"]]):
                    raise RuntimeError("跳过已完成阶段失败")
                workflows.forget_stage(task_id)
            else:
                workflows.guard_stage(task_id, stage)
            return CustomAction.RunResult(success=True)
        except Exception as exc:
            logger.error(f"阶段启动失败：{exc}")
            return CustomAction.RunResult(success=False)


@AgentServer.custom_action("CompleteWorkflowStage")
class CompleteWorkflowStage(CustomAction):
    def run(self, context, argv):
        task_id = argv.task_detail.task_id
        try:
            stage = workflows.active_stage(task_id)
            if stage is None:
                raise ValueError("没有执行中的阶段，拒绝登记完成")
            workflows.stage_store.mark(stage, "completed")
            workflows.forget_stage(task_id)
            return CustomAction.RunResult(success=True)
        except Exception as exc:
            logger.error(f"阶段完成登记失败：{exc}")
            return CustomAction.RunResult(success=False)


@AgentServer.custom_action("PauseWorkflowStage")
class PauseWorkflowStage(CustomAction):
    def run(self, context, argv):
        pause_workflow(argv.task_detail.task_id, "阶段识别或动作失败")
        return CustomAction.RunResult(success=True)
