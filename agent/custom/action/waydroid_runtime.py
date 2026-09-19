"""Waydroid / ADB 拉起、重启，以及启动后进程监视开关。"""

from __future__ import annotations

from copy import deepcopy

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.action.general import (
    _get_remembered_game_package,
    _get_start_app_package,
)
from custom.game_process_watch import game_process_watch
from utils.logger import logger
from utils.waydroid_host import restart_waydroid_session


def _reconnect_controller(context: Context) -> bool:
    controller = context.tasker.controller
    try:
        job = controller.post_connection()
        job.wait()
        if not job.succeeded:
            logger.error("Maa controller post_connection 未成功")
            return False
        if not controller.connected:
            logger.error("Maa controller 重连后仍未 connected")
            return False
        logger.info("Maa controller 已重新连接")
        return True
    except Exception as exc:
        logger.exception(f"Maa controller 重连失败: {exc}")
        return False


@AgentServer.custom_action("RestartWaydroid")
class RestartWaydroid(CustomAction):
    """启动后进程消失时重启 Waydroid session，并恢复 ADB / controller。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        package = _get_remembered_game_package() or _get_start_app_package(context)
        game_process_watch.consume_waydroid_restart_request()
        game_process_watch.disarm()
        logger.error(
            f"RestartWaydroid: 启动后游戏进程消失，重启 Waydroid "
            f"(package={package!r}, task_id={argv.task_detail.task_id})"
        )
        try:
            restart_waydroid_session()
        except Exception as exc:
            logger.exception(f"RestartWaydroid 失败: {exc}")
            return CustomAction.RunResult(success=False)

        if not _reconnect_controller(context):
            return CustomAction.RunResult(success=False)
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("ArmGameProcessWatch")
class ArmGameProcessWatch(CustomAction):
    """StartApp 完成后开始监视：之后连续 pidof 不到即判定进程消失。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        package = _get_remembered_game_package() or _get_start_app_package(context)
        game_process_watch.arm()
        logger.info(
            f"ArmGameProcessWatch: 已开始监视 package={package!r} "
            f"(task_id={argv.task_detail.task_id})"
        )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("DisarmGameProcessWatch")
class DisarmGameProcessWatch(CustomAction):
    """主动关游戏/走失败分支前停止监视，避免误判进程消失。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        game_process_watch.disarm()
        logger.info(
            f"DisarmGameProcessWatch: 已停止监视 (task_id={argv.task_detail.task_id})"
        )
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("HandleGameCrash")
class HandleGameCrash(CustomAction):
    """闪退标志命中后：启动任务里去重启 Waydroid；业务任务交还调度。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        from custom.deferred_tasks import (
            ManagedTask,
            effective_task_entry,
            managed_task_queue,
            pipeline_override_for_entry,
        )

        entry = effective_task_entry(argv.task_detail.entry)
        node_name = argv.node_name
        if entry == "启动游戏entry":
            context.override_next(node_name, ["若闪退需重启Waydroid"])
            logger.error(
                f"HandleGameCrash: 启动任务内闪退，转入重启 Waydroid "
                f"(task_id={argv.task_detail.task_id})"
            )
            return CustomAction.RunResult(success=True)

        task_id = argv.task_detail.task_id
        current = managed_task_queue.requeue_current(task_id)
        if current is None:
            logger.error(
                f"HandleGameCrash: 无法取回当前任务 "
                f"(task_id={task_id}, entry={entry!r})"
            )
            return CustomAction.RunResult(success=False)

        startup_override = pipeline_override_for_entry("启动游戏entry")
        managed_task_queue.prepend_pending(
            ManagedTask(
                name="闪退恢复：启动游戏",
                entry="启动游戏entry",
                pipeline_override=deepcopy(startup_override),
                base_pipeline_override=deepcopy(startup_override),
            )
        )
        context.override_next(node_name, ["AgentSchedulerRecoveryStop"])
        logger.error(
            f"HandleGameCrash: 业务任务闪退，将重启 Waydroid 后恢复 "
            f"{entry!r} (task_id={task_id})"
        )
        return CustomAction.RunResult(success=True)
