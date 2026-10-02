from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.interruptible import TaskStopRequested, interruptible_sleep


@AgentServer.custom_action("my_3v3_kn_yan_p2")
class my_3v3_kn_yan_p2(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        """
        3v3 点击动作
        直接在代码中添加点击逻辑，格式：
        # 点击[x,y]delay t
        其中 x,y 是点击坐标，t 是延迟时间（毫秒）
        """
        del argv
        try:
            # ===================
            # p2 录制未到：挂机占住流程，可被停止打断
            # ===================
            for _ in range(120):
                if not interruptible_sleep(context, 5000):
                    raise TaskStopRequested

            # ===================
            # 结束点击序列
            # ===================

            return CustomAction.RunResult(success=True)
        except TaskStopRequested:
            return CustomAction.RunResult(success=False)
        except Exception as e:
            import logging

            logging.error(f"执行3v3点击时出错: {e}")
            print(f"执行3v3点击时出错: {e}")
            return CustomAction.RunResult(success=False)
