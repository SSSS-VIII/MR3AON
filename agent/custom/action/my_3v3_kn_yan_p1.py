from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction


from custom.interruptible import (
    ClickDelayState,
    TaskStopRequested,
    bind_parkour_clicks,
)


@AgentServer.custom_action("my_3v3_kn_yan_p1")
class my_3v3_kn_yan_p1(CustomAction):
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
            # 20261002-180115 录制；粘贴前已对每段 delay 减去
            # interruptible.ClickDelayState 的 +60ms 修正，避免相对人手
            # 录制基线每步累加变慢。主偏移可改下面首段。
            # click(200, 620, t) 为下翻
            # doubleclick(200, 620, t) 为下翻连点两次
            # click(1100, 620, t) 为跳跃
            # ===================

            click(1, 1, 50)

            click(1100, 620, 527)  # 跳跃
            click(1100, 620, 677)  # 跳跃
            click(1100, 620, 2282)  # 跳跃
            click(1100, 620, 586)  # 跳跃
            click(1100, 620, 655)  # 跳跃
            click(1100, 620, 1182)  # 跳跃
            click(1100, 620, 569)  # 跳跃
            click(1100, 620, 482)  # 跳跃
            click(1100, 620, 528)  # 跳跃
            click(200, 620, 373)  # 下翻
            click(1100, 620, 428)  # 跳跃
            click(1100, 620, 235)  # 跳跃
            click(200, 620, 257)  # 下翻
            click(1100, 620, 371)  # 跳跃
            click(1100, 620, 621)  # 跳跃
            click(1100, 620, 453)  # 跳跃
            click(200, 620, 89)  # 下翻
            click(1100, 620, 149)  # 跳跃
            click(1100, 620, 1070)  # 跳跃
            click(1100, 620, 639)  # 跳跃
            click(1100, 620, 623)  # 跳跃
            click(1100, 620, 250)  # 跳跃
            click(200, 620, 72)  # 下翻
            click(1100, 620, 203)  # 跳跃
            click(1100, 620, 1508)  # 跳跃
            click(1100, 620, 413)  # 跳跃
            click(1100, 620, 118)  # 跳跃
            click(200, 620, 113)  # 下翻
            click(1100, 620, 341)  # 跳跃
            click(1100, 620, 97)  # 跳跃
            click(200, 620, 578)  # 下翻
            click(1100, 620, 303)  # 跳跃
            click(200, 620, 396)  # 下翻
            click(1100, 620, 234)  # 跳跃
            click(1100, 620, 108)  # 跳跃
            click(200, 620, 148)  # 下翻
            click(1100, 620, 312)  # 跳跃
            click(1100, 620, 58)  # 跳跃
            click(200, 620, 727)  # 下翻
            click(1100, 620, 544)  # 跳跃
            click(1100, 620, 1432)  # 跳跃
            click(1100, 620, 438)  # 跳跃
            click(1100, 620, 87)  # 跳跃
            click(200, 620, 427)  # 下翻
            click(1100, 620, 415)  # 跳跃
            click(1100, 620, 98)  # 跳跃
            click(200, 620, 338)  # 下翻
            click(1100, 620, 178)  # 跳跃
            click(1100, 620, 331)  # 跳跃
            click(1100, 620, 1511)  # 跳跃
            click(1100, 620, 0)  # 跳跃

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
