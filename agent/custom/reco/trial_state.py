"""忍村试炼 Agent 状态分支。"""

from __future__ import annotations

from typing import Optional, Union

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType

from custom.trial_state import trial_challenge_state


@AgentServer.custom_recognition("TrialMaxRemainingReachedThree")
class TrialMaxRemainingReachedThree(CustomRecognition):
    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        del context, argv
        maximum = trial_challenge_state.max_remaining()
        if maximum < 3:
            return None
        return CustomRecognition.AnalyzeResult(
            box=[0, 0, 1, 1],
            detail={"max_remaining": maximum},
        )
