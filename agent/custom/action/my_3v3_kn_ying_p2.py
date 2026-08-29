from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.interruptible import ClickDelayState, interruptible_click, click_delay_calibrate, TaskStopRequested

@AgentServer.custom_action("my_3v3_kn_ying_p2")
class my_3v3_kn_ying_p2(CustomAction):
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
            click(1, 1, 8750 - click_delay_calibrate())
            click(200, 620, 1000)
            click(1100, 620, 430)
            click(200, 620, 1200)
            click(1100, 620, 1620)
            click(200, 620, 800)
            click(1100, 620, 500)
            click(200, 620, 800)
            click(1100, 620, 1400)
            click(200, 620, 1900)
            click(1100, 620, 300)
            click(1100, 620, 300)
            click(1100, 620, 300)
            click(200, 620, 1500)
            click(1100, 620, 800)
            click(1100, 620, 1600)
            click(1100, 620, 300)
            click(1100, 620, 300)
            click(200, 620, 2600)
            click(200, 620, 700)
            click(1100, 620, 1100)
            click(1100, 620, 1000)
            click(1100, 620, 300)
            click(1100, 620, 400)
            click(200, 620, 400)
            click(1100, 620, 300)
            click(1100, 620, 700)
            click(1100, 620, 400)
            click(200, 620, 900)
            click(1100, 620, 300)
            click(1100, 620, 240)
            click(200, 620, 200)
            click(1100, 620, 200)
            click(1100, 620, 1880)
            click(1100, 620, 590)
            click(1100, 620, 800)
            click(1100, 620, 800)
            click(1100, 620, 660)
            click(200, 620, 2100)
            click(1100, 620, 600)
            click(1100, 620, 600)
            click(1100, 620, 5400)
            click(1100, 620, 900)
            click(1100, 620, 650)
            click(200, 620, 1150)
            click(1100, 620, 480)
            click(200, 620, 480)
            click(1100, 620, 480)
            click(200, 620, 330)
            click(1100, 620, 280)
            click(1100, 620, 280)
            click(200, 620, 480)
            click(1100, 620, 280)
            click(1100, 620, 280)
            click(200, 620, 550)

            click(1100, 620, 200)
            click(200, 620, 500)

            click(1100, 620, 200)
            click(200, 620, 590)

            click(1100, 620, 400)
            click(1100, 620, 400)
            click(1100, 620, 2400)
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
