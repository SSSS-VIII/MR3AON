"""结算确认页截图（不含点击，点击留给后续 DirectHit 节点）。"""

from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.pipeline_params import parse_pipeline_json_param
from custom.reward_shots import save_image_array
from utils.logger import logger


def _grab_image(context: Context) -> Any:
    ctrl = context.tasker.controller
    # 优先用识别当帧缓存，避免再等一轮截屏
    try:
        cached = ctrl.cached_image
        if cached is not None:
            return cached
    except Exception:
        pass
    try:
        return ctrl.post_screencap().wait().get()
    except Exception as exc:
        logger.warning(f"SaveRewardScreenshot: 截屏失败: {exc}")
        return None


@AgentServer.custom_action("SaveRewardScreenshot")
class SaveRewardScreenshot(CustomAction):
    """保存奖励结算截图到 debug/reward_shots/<dir>/。

    custom_action_param:
      dir: 目录名（必填），如「每日悬赏」「S_SS+」「家族战」
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        try:
            param = parse_pipeline_json_param(argv.custom_action_param)
            dir_name = param.get("dir")
            if not isinstance(dir_name, str) or not dir_name.strip():
                logger.error("SaveRewardScreenshot: 缺少 dir 参数")
                return CustomAction.RunResult(success=False)

            image = _grab_image(context)
            path = save_image_array(image, dir_name.strip())
            if path is None:
                logger.warning("SaveRewardScreenshot: 保存失败")
                return CustomAction.RunResult(success=False)
            return CustomAction.RunResult(success=True)
        except Exception as exc:
            logger.exception(f"SaveRewardScreenshot 失败: {exc}")
            return CustomAction.RunResult(success=False)
