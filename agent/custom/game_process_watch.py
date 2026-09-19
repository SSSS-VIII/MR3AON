"""游戏进程闪退监视：先确认活过，再持续看它是否消失。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class GameProcessWatch:
    """StartApp 后开始观察；必须先见到进程，之后再消失才算闪退。"""

    miss_threshold: int = 2
    poll_interval_sec: float = 5.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _watching: bool = False
    _seen_alive: bool = False
    _miss_streak: int = 0
    _waydroid_restart_requested: bool = False
    _recovering: bool = False
    _last_poll_at: float = 0.0

    def arm(self) -> None:
        """开始观察。此时还不算已启动成功，要等 note_present。"""
        with self._lock:
            self._watching = True
            self._seen_alive = False
            self._miss_streak = 0
            self._recovering = False
            self._last_poll_at = 0.0

    def disarm(self) -> None:
        with self._lock:
            self._watching = False
            self._seen_alive = False
            self._miss_streak = 0
            self._recovering = False

    @property
    def watching(self) -> bool:
        with self._lock:
            return self._watching

    @property
    def seen_alive(self) -> bool:
        with self._lock:
            return self._seen_alive

    def note_present(self) -> None:
        with self._lock:
            if not self._watching:
                return
            self._seen_alive = True
            self._miss_streak = 0

    def note_missing(self) -> bool:
        """进程不在。仅当曾经活过且连续 miss 达到阈值时返回 True（判定闪退）。"""
        with self._lock:
            if not self._watching or not self._seen_alive or self._recovering:
                return False
            self._miss_streak += 1
            return self._miss_streak >= self.miss_threshold

    def begin_recovery(self) -> bool:
        """占住恢复权，避免 sink/识别同时触发多次重启。"""
        with self._lock:
            if self._recovering:
                return False
            self._recovering = True
            self._watching = False
            self._seen_alive = False
            self._miss_streak = 0
            self._waydroid_restart_requested = True
            return True

    def peek_waydroid_restart_request(self) -> bool:
        with self._lock:
            return self._waydroid_restart_requested

    def consume_waydroid_restart_request(self) -> bool:
        with self._lock:
            requested = self._waydroid_restart_requested
            self._waydroid_restart_requested = False
            return requested

    def request_waydroid_restart(self) -> None:
        with self._lock:
            self._waydroid_restart_requested = True

    def clear_recovery(self) -> None:
        with self._lock:
            self._recovering = False

    def should_poll(self, now: float | None = None) -> bool:
        ts = time.monotonic() if now is None else now
        with self._lock:
            if not self._watching or self._recovering:
                return False
            if ts - self._last_poll_at < self.poll_interval_sec:
                return False
            self._last_poll_at = ts
            return True


game_process_watch = GameProcessWatch()
