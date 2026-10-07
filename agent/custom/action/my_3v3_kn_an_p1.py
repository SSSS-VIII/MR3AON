from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction


from custom.interruptible import (
    ClickDelayState,
    TaskStopRequested,
    bind_parkour_clicks,
    click_delay_calibrate,
)


@AgentServer.custom_action("my_3v3_kn_an_p1")
class my_3v3_kn_an_p1(CustomAction):
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
            click, doubleclick = bind_parkour_clicks(context, delay_state)

            # ===================
            # 在这里添加你的点击序列
            # ===================
            # click(200, 620, t) 为下翻
            # doubleclick(200, 620, t) 为下翻连点两次
            # click(1100, 620, t) 为跳跃
            click(1, 1, 6050 - click_delay_calibrate())
            click(1100, 620, 3400)
            click(1100, 620, 2230)
            click(1100, 620, 2900)
            click(1100, 620, 1270)
            click(1100, 620, 3820)
            click(1100, 620, 7100)
            click(1100, 620, 300)
            click(1100, 620, 2250)
            click(1100, 620, 280)
            click(1100, 620, 280)
            click(1100, 620, 10000)
            click(200, 620, 1500)
            click(200, 620, 1500)
            click(200, 620, 1500)
            click(200, 620, 1500)
            click(200, 620, 1500)
            click(200, 620, 1500)
            click(200, 620, 1500)
            click(200, 620, 1500)
            click(200, 620, 1500)
            click(200, 620, 1500)
            click(200, 620, 1500)

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
