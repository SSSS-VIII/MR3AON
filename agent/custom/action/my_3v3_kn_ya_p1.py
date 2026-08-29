from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.interruptible import ClickDelayState, interruptible_click, click_delay_calibrate, TaskStopRequested

@AgentServer.custom_action("my_3v3_kn_ya_p1")
class my_3v3_kn_ya_p1(CustomAction):
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
        try:
            delay_state = ClickDelayState()

            def click(x, y, delay_ms=0):
                if not interruptible_click(context, x, y, delay_ms, delay_state=delay_state):
                    raise TaskStopRequested

            # ===================
            # 在这里添加你的点击序列
            # ===================
            # click(200, 620, t) 为下翻
            # click(1100, 620, t) 为跳跃
            click(1, 1, 8980 - click_delay_calibrate())
            click(200, 620, 3250)
            click(1100, 620, 250)
            click(1100, 620, 1820)
            click(200, 620, 363)
            click(1100, 620, 350)
            click(1100, 620, 350)
            click(1100, 620, 5300)
            click(1100, 620, 320)
            click(1100, 620, 1240)
            click(200, 620, 8000)
            click(1100, 620, 400)
            click(1100, 620, 10850)


            click(1100, 620, 1000)
            click(1100, 620, 500)
            click(1100, 620, 1200)
            click(1100, 620, 300)
            click(1100, 620, 4000)
            # click(1250,50,0)

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
