"""同屏竞速跑酷：下滑冲刺 + 二段跳，并按概率随机释放一张技能卡。"""

import random
import time
from typing import Any, Tuple

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.pipeline_params import parse_pipeline_json_param
from utils import logger

# target [x, y, w, h] 区域中心点
_JUMP_RECT = (1080, 600, 50, 50)
_SKILL_RECTS: Tuple[Tuple[int, int, int, int], ...] = (
    (357, 606, 50, 50),
    (496, 570, 50, 50),
    (610, 570, 50, 50),
    (724, 570, 50, 50),
    (875, 606, 50, 50),
)
_SWIPE_BEGIN = (200, 610)
_SWIPE_END = (200, 660)


def _rect_center(rect: Tuple[int, int, int, int]) -> Tuple[int, int]:
    x, y, w, h = rect
    return x + w // 2, y + h // 2


def _coerce_probability(value: Any, default: float) -> float:
    """解析 [0, 1] 概率；非法时返回 default。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        v = float(value)
        if 0.0 <= v <= 1.0:
            return v
        logger.warning(f"sync_race_parkour: skill_phase_chance 非法 ({value})，使用 {default}")
        return default
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return default
        try:
            v = float(s)
        except ValueError:
            logger.warning(f"sync_race_parkour: skill_phase_chance 非法 ({value!r})，使用 {default}")
            return default
        if 0.0 <= v <= 1.0:
            return v
        logger.warning(f"sync_race_parkour: skill_phase_chance 非法 ({value!r})，使用 {default}")
        return default
    logger.warning(
        f"sync_race_parkour: skill_phase_chance 类型不支持 ({type(value).__name__})，使用 {default}"
    )
    return default


def _coerce_positive_int(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return default
        try:
            v = int(s)
        except ValueError:
            return default
        return v if v >= 0 else default
    return default


@AgentServer.custom_action("sync_race_parkour")
class sync_race_parkour(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        """
        同屏竞速单次跑酷动作。

        custom_action_param（可选）:
            {
                "skill_phase_chance": 0.35,  // 本次是否尝试放技能的概率，默认 0.35
                "step_delay_ms": 150,        // 各步骤间隔（毫秒），默认 150
                "swipe_duration_ms": 150     // 下滑滑动时长（毫秒），默认 150
            }

        流程：
            1. 下滑冲刺 → 跳跃 ×2
            2. 以 skill_phase_chance 判定；命中则在五个技能位中随机点击其一
        """
        try:
            param = parse_pipeline_json_param(argv.custom_action_param)
            skill_chance = _coerce_probability(param.get("skill_phase_chance"), 0.35)
            step_delay_ms = _coerce_positive_int(param.get("step_delay_ms"), 150)
            swipe_duration_ms = _coerce_positive_int(param.get("swipe_duration_ms"), 150)

            ctrl = context.tasker.controller

            def sleep_step() -> None:
                if step_delay_ms > 0:
                    time.sleep(step_delay_ms / 1000)

            def click_rect(rect: Tuple[int, int, int, int]) -> None:
                x, y = _rect_center(rect)
                ctrl.post_click(x, y).wait()

            # 第一部分：下滑 + 二段跳
            x1, y1 = _SWIPE_BEGIN
            x2, y2 = _SWIPE_END
            ctrl.post_swipe(x1, y1, x2, y2, swipe_duration_ms).wait()
            sleep_step()

            click_rect(_JUMP_RECT)
            sleep_step()
            click_rect(_JUMP_RECT)
            sleep_step()

            # 第二部分：概率触发，随机一张技能卡
            if random.random() < skill_chance:
                skill_idx = random.randrange(len(_SKILL_RECTS))
                click_rect(_SKILL_RECTS[skill_idx])
                logger.debug(
                    f"sync_race_parkour: 释放技能 {skill_idx} (chance={skill_chance})"
                )
            else:
                logger.debug(f"sync_race_parkour: 跳过技能 (chance={skill_chance})")

            return CustomAction.RunResult(success=True)
        except Exception as e:
            logger.exception(f"sync_race_parkour 执行出错: {e}")
            return CustomAction.RunResult(success=False)
