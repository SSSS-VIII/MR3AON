"""忍村试炼在 Agent 生命周期内共享的观察状态。"""

from __future__ import annotations

import threading


class TrialChallengeState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._max_remaining = 0

    def record_remaining(self, remaining: int) -> int:
        with self._lock:
            self._max_remaining = max(self._max_remaining, remaining)
            return self._max_remaining

    def max_remaining(self) -> int:
        with self._lock:
            return self._max_remaining


trial_challenge_state = TrialChallengeState()
