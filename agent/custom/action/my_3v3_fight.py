import time
from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

@AgentServer.custom_action("my_3v3_fight")
class my_3v3_fight(CustomAction):
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
            # 执行点击操作的函数
            def click(x, y, delay_ms=0):
                """执行点击并延迟"""
                context.tasker.controller.post_click(x, y).wait()
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000)
            
            # ===================
            # 在这里添加你的点击序列
            # ===================
            # click(80, 360, t) 为大招原点
            # click(180, 260, t) 为小椒1式
            # click(380, 620, t) 为武器1
            # click(900, 620, t) 为武器2
            # click(520, 590, t) 为卡牌1
            # click(640, 590, t) 为卡牌2
            # click(750, 590, t) 为卡牌3

            # 两个武器
            click(380, 620, 0)
            click(900, 620, 0)

            # 大招开启
            click(80, 360, 0)
            click(180, 260, 2000)
            
            # 两个武器
            click(380, 620, 0)
            click(900, 620, 0)

            # 大招后续
            click(80, 360, 0)
            click(180, 260, 2000)

            # 两个武器
            click(380, 620, 0)
            click(900, 620, 0)

            # 大招后续
            click(80, 360, 0)
            click(180, 260, 2000)

            # 两个武器
            click(380, 620, 0)
            click(900, 620, 0)

            # 大招后续
            click(80, 360, 0)
            click(180, 260, 2000)

            # 两个武器
            click(380, 620, 0)
            click(900, 620, 0)

            # 大招后续
            click(80, 360, 0)
            click(180, 260, 2000)

            # 大招后续
            click(80, 360, 0)
            click(180, 260, 2000)

            # 三个卡牌
            click(750, 590, 100)
            click(640, 590, 100)
            click(520, 590, 100)

            click(80, 360, 200)
            click(180, 260, 200)
            # 再次三个卡牌
            click(750, 590, 100)
            click(640, 590, 100)
            click(520, 590, 100)

            click(80, 360, 200)
            click(180, 260, 200)
            # 再再次三个卡牌  
            click(750, 590, 100)
            click(640, 590, 100)
            click(520, 590, 100)

            click(80, 360, 200)
            click(180, 260, 200)

            click(80, 360, 200)
            click(180, 260, 200)
            click(80, 360, 200)
            click(180, 260, 200)
            click(80, 360, 200)
            click(180, 260, 200)
            click(80, 360, 200)
            click(180, 260, 200)
            click(80, 360, 200)
            click(180, 260, 200)
            click(80, 360, 200)
            click(180, 260, 200)

            # ===================
            # 结束点击序列
            # ===================
            
            return CustomAction.RunResult(success=True)
        except Exception as e:
            import logging
            logging.error(f"执行3v3点击时出错: {e}")
            print(f"执行3v3点击时出错: {e}")
            return CustomAction.RunResult(success=False)
