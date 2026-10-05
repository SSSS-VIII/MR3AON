from __future__ import annotations

import time
from typing import Dict, Optional

from utils import logger


class LoopDeadlineStore:
    """
    按 task_id + scope 存储循环总时长截止时间（time.perf_counter() 时刻）。
    task_id 变化时清空全部条目，避免跨任务串线。
    """

    _deadline_at: Dict[str, float] = {}
    _expired_dump_done: Dict[str, bool] = {}
    _last_task_id: int = -1

    @classmethod
    def _key(cls, task_id: int, scope: str) -> str:
        return f"{task_id}\t{scope}"

    @classmethod
    def _sync_task(cls, task_id: int) -> None:
        if task_id != cls._last_task_id:
            cls._deadline_at.clear()
            cls._expired_dump_done.clear()
            cls._last_task_id = task_id

    @classmethod
    def arm(cls, task_id: int, scope: str, duration_ms: int) -> None:
        cls._sync_task(task_id)
        if duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")
        key = cls._key(task_id, scope)
        cls._deadline_at[key] = time.perf_counter() + duration_ms / 1000.0
        cls._expired_dump_done.pop(key, None)

    @classmethod
    def reset(cls, task_id: int, scope: Optional[str] = None) -> None:
        """scope 为 None 时移除当前 task 下所有 scope 的截止时间。"""
        cls._sync_task(task_id)
        if scope is None:
            prefix = f"{task_id}\t"
            for k in list(cls._deadline_at.keys()):
                if k.startswith(prefix):
                    del cls._deadline_at[k]
                    cls._expired_dump_done.pop(k, None)
        else:
            key = cls._key(task_id, scope)
            cls._deadline_at.pop(key, None)
            cls._expired_dump_done.pop(key, None)

    @classmethod
    def is_armed(cls, task_id: int, scope: str) -> bool:
        cls._sync_task(task_id)
        return cls._key(task_id, scope) in cls._deadline_at

    @classmethod
    def is_expired(cls, task_id: int, scope: str) -> bool:
        """未 arm 时视为未超时（识别不命中）。"""
        cls._sync_task(task_id)
        end = cls._deadline_at.get(cls._key(task_id, scope))
        if end is None:
            return False
        return time.perf_counter() >= end

    @classmethod
    def claim_expired_dump(cls, task_id: int, scope: str) -> bool:
        """
        同一轮 arm 到期后仅允许领取一次截图保存权。
        未到期 / 未 arm / 已领取过 → False。
        """
        cls._sync_task(task_id)
        key = cls._key(task_id, scope)
        if key not in cls._deadline_at:
            return False
        if time.perf_counter() < cls._deadline_at[key]:
            return False
        if cls._expired_dump_done.get(key):
            return False
        cls._expired_dump_done[key] = True
        return True
