from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.interruptible import TaskStopRequested
from custom.sequence_timing import bind_stage_clicks


@AgentServer.custom_action("qh_level_2_8")
class qh_level_2_8(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        """
        新手关卡点击动作
        直接在代码中添加点击逻辑，格式：
        # 点击[x,y]delay t
        其中 x,y 是点击坐标，t 是延迟时间（毫秒）
        """
        try:

            click = bind_stage_clicks(context, argv.task_detail.task_id)

            # ===================
            # 在这里添加你的点击序列
            # ===================
            # click(200, 620, t) 为下翻
            # click(1100, 620, t) 为跳跃
            click(1100, 620, 2300)

            click(1100, 620, 200)
            click(1100, 620, 600)
            click(200, 620, 400)

            click(1100, 620, 200)
            click(1100, 620, 600)
            click(200, 620, 900)

            click(1100, 620, 200)
            click(1100, 620, 600)
            click(200, 620, 30000)
            click(1100, 620, 10000)
            click(200, 620, 2000)
            click(1100, 620, 4000)
            click(200, 620, 3000)
            click(1100, 620, 3000)
            click(200, 620, 3000)
            click(1100, 620, 3000)
            click(200, 620, 3000)
            click(1100, 620, 300)
            click(1100, 620, 300)
            click(1100, 620, 5200)

            click(1100, 620, 200)
            click(1100, 620, 600)
            click(1100, 620, 1400)

            click(1100, 620, 200)
            click(1100, 620, 600)
            click(1100, 620, 800)

            click(1100, 620, 200)
            click(1100, 620, 600)
            click(1100, 620, 500)

            click(1100, 620, 200)
            click(1100, 620, 600)
            click(1100, 620, 16000)

            click(1100, 620, 800)
            click(1100, 620, 800)
            click(200, 620, 7000)

            click(1100, 620, 3800)
            click(200, 620, 2500)
            click(1100, 620, 4000)
            click(200, 620, 2500)
            click(1100, 620, 800)
            click(380, 620, 200)
            click(1100, 620, 400)
            click(1100, 620, 400)
            click(1100, 620, 3000)

            # ===================
            # 结束点击序列
            # ===================

            return CustomAction.RunResult(success=True)
        except TaskStopRequested:
            return CustomAction.RunResult(success=False)
        except Exception as e:
            import logging

            logging.error(f"起号关卡点击失败: {e}")
            print(f"起号关卡点击失败: {e}")
            return CustomAction.RunResult(success=False)
