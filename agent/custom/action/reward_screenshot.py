"""结算确认页截图（不含点击，点击留给后续 DirectHit 节点）。"""

from __future__ import annotations

from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.pipeline_params import parse_pipeline_json_param
from custom.reward_shots import save_image_array
from utils.logger import logger


def _grab_image(context: Context, *, fresh: bool = False) -> Any:
    ctrl = context.tasker.controller
    if not fresh:
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
      dir: 目录名（必填）
      burst_replace: 可选 bool
      burst_gap_sec: 可选 float，无 burst_entry 时的短间隔同场秒数，默认 10
      burst_entry: 可选。保存时若与上次入口相同则覆盖；同 next 列表命中其它候选则新开
      fresh_capture: 可选 bool。true 时重新截屏
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

            dir_name = dir_name.strip()
            burst_replace = bool(param.get("burst_replace", False))
            fresh = bool(param.get("fresh_capture", False))
            burst_entry = param.get("burst_entry")
            if not isinstance(burst_entry, str):
                burst_entry = ""
            burst_entry = burst_entry.strip()

            extra: dict[str, Any] = {"node_name": argv.node_name or ""}
            gap_raw = param.get("burst_gap_sec", None)
            if gap_raw is not None:
                try:
                    extra["burst_gap_sec"] = float(gap_raw)
                except (TypeError, ValueError):
                    logger.warning(
                        f"SaveRewardScreenshot: 忽略非法 burst_gap_sec={gap_raw!r}"
                    )

            if burst_replace:
                # 入口即本节点：未显式写 burst_entry 时用 node_name
                extra["burst_entry"] = burst_entry or (argv.node_name or "").strip()

            image = _grab_image(context, fresh=fresh)
            path = save_image_array(
                image,
                dir_name,
                burst_replace=burst_replace,
                **extra,
            )
            if path is None:
                logger.warning("SaveRewardScreenshot: 保存失败")
                return CustomAction.RunResult(success=False)
            return CustomAction.RunResult(success=True)
        except Exception as exc:
            logger.exception(f"SaveRewardScreenshot 失败: {exc}")
            return CustomAction.RunResult(success=False)
