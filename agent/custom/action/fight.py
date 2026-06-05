import time
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.pipeline_params import parse_pipeline_json_param
from utils import logger


def _coerce_fight_mode(value: Any) -> int:
    """解析 mode，合法值为 0–3；缺省或非法时返回 0。"""
    if value is None:
        return 0
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        if value in (0, 1, 2, 3):
            return value
        logger.warning(f"fight: mode 非法 ({value})，使用 0")
        return 0
    if isinstance(value, str):
        s = value.strip()
        if s in ("0", "1", "2", "3"):
            return int(s)
        if s == "":
            return 0
        logger.warning(f"fight: mode 非法 ({value!r})，使用 0")
        return 0
    logger.warning(f"fight: mode 类型不支持 ({type(value).__name__})，使用 0")
    return 0


@AgentServer.custom_action("fight")
class fight(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        """
        战斗开大连点。

        custom_action_param（可选）: { "mode": 0 | 1 | 2 | 3 }

        mode:
            0 - 通用（大招原点 + 小椒 1 式）
            1 - 其他角色（仅大招原点）
            2 - 双焰小椒（大招原点 + 小椒 1 式）
            3 - 剑心/卫鲤（大招原点一次 + 卫鲤 2 式）

        每日悬赏等任务会在识别角色后通过 NodeOverride 覆盖 mode；
        未覆盖或未传参时默认为 0。
        """
        try:
            param = parse_pipeline_json_param(argv.custom_action_param)
            mode = _coerce_fight_mode(param.get("mode", 0))

            def click(x: int, y: int, delay_ms: int = 0) -> None:
                context.tasker.controller.post_click(x, y).wait()
                if delay_ms > 0:
                    time.sleep(delay_ms / 1000)

            # (80, 360) 大招原点；(180, 260) 小椒 1 式；(210, 350) 卫鲤 2 式
            if mode == 0:
                for _ in range(40):
                    click(80, 360, 100)
                    click(180, 260, 100)
            elif mode == 1:
                for _ in range(50):
                    click(80, 360, 200)
            elif mode == 2:
                for _ in range(25):
                    click(80, 360, 100)
                    click(180, 260, 100)
            elif mode == 3:
                click(80, 360, 200)
                for _ in range(25):
                    click(210, 350, 200)

            return CustomAction.RunResult(success=True)
        except Exception as e:
            logger.exception(f"fight 执行出错: {e}")
            return CustomAction.RunResult(success=False)
