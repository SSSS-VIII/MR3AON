"""记录忍村试炼剩余挑战次数。"""

from __future__ import annotations

import re
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from custom.trial_state import trial_challenge_state
from utils.logger import logger


_REMAINING_COUNT = re.compile(r"剩余挑战次数\D*([0-9]+)")


def _recognition_texts(argv: CustomAction.RunArg) -> list[str]:
    results: list[Any] = []
    if argv.reco_detail.best_result is not None:
        results.append(argv.reco_detail.best_result)
    results.extend(argv.reco_detail.filtered_results or [])
    return [
        text
        for result in results
        if isinstance((text := getattr(result, "text", None)), str)
    ]


@AgentServer.custom_action("RecordTrialRemainingChallengeMax")
class RecordTrialRemainingChallengeMax(CustomAction):
    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        del context
        for text in _recognition_texts(argv):
            match = _REMAINING_COUNT.search(text)
            if match is None:
                continue
            remaining = int(match.group(1))
            maximum = trial_challenge_state.record_remaining(remaining)
            logger.info(
                f"忍村试炼剩余挑战次数: current={remaining}, max_seen={maximum}"
            )
            return CustomAction.RunResult(success=True)

        logger.error("RecordTrialRemainingChallengeMax: 识别结果中未找到剩余挑战次数")
        return CustomAction.RunResult(success=False)
