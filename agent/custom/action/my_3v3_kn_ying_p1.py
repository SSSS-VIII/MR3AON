from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction


from custom.interruptible import (
    ClickDelayState,
    TaskStopRequested,
    bind_parkour_clicks,
    click_delay_calibrate,
)


@AgentServer.custom_action("my_3v3_kn_ying_p1")
class my_3v3_kn_ying_p1(CustomAction):
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
            click(1, 1, 2950 - click_delay_calibrate())
            click(1100, 620, 320)
            click(1100, 620, 750)
            click(200, 620, 400)
            click(1100, 620, 300)
            click(1100, 620, 550)
            click(200, 620, 650)
            click(1100, 620,2900)

            click(1100, 620, 300)
            click(1100, 620,670)
            click(200, 620, 100)
            click(1100, 620,300)
            click(1100, 620,1000)

            click(1100, 620,300)
            click(1100, 620,500)
            click(200, 620, 450)

            click(1100, 620,300)
            click(200, 620, 300)

            click(1100, 620,300)
            click(1100, 620,300)
            click(200, 620, 400)

            click(1100, 620,400)
            click(200, 620, 3000)

            click(200, 620, 1000)
            click(200, 620, 1000)
            click(200, 620, 1000)
            click(200, 620, 1000)
            click(200, 620, 4500)

            click(1100, 620,300)
            click(1100, 620,300)
            click(200, 620, 1800)

            click(1100, 620,300)
            click(1100, 620,300)
            click(200, 620, 900)

            click(1100, 620,300)
            click(1100, 620,300)
            click(200, 620, 500)


            click(1100, 620,300)
            click(1100, 620,300)
            click(200, 620, 400)

            click(1100, 620,300)
            click(1100, 620,300)
            click(200, 620, 200)

            click(1100, 620,300)
            click(1100, 620,300)
            click(200, 620, 600)

            click(200, 620, 1000)
            click(200, 620, 1000)
            click(200, 620, 5000)

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
