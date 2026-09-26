"""启动 / 关闭 Agent 内嵌 Textual TUI。"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from utils.logger import logger, setup_logger


def tui_should_run() -> bool:
    flag = os.environ.get("MR3A_TUI", "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    # 默认：交互式 TTY 才开；被重定向时保持纯日志
    return sys.stderr.isatty()


def _quiet_console_logging() -> None:
    """TUI 占住终端时，控制台只留文件日志，避免冲屏。"""
    setup_logger(console_level="ERROR")


def _cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode(errors="replace")


def _stat_fields(pid: int) -> list[str] | None:
    """返回 /proc/pid/stat 中 comm 之后的字段：state ppid pgrp session ..."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    rparen = stat.rfind(")")
    if rparen < 0:
        return None
    return stat[rparen + 2 :].split()


def _ppid(pid: int) -> int:
    fields = _stat_fields(pid)
    if not fields or len(fields) < 2:
        return 0
    try:
        return int(fields[1])
    except ValueError:
        return 0


def _sid(pid: int) -> int:
    fields = _stat_fields(pid)
    if not fields or len(fields) < 4:
        return 0
    try:
        return int(fields[3])
    except ValueError:
        return 0


def _fd_tty(pid: int, fd: int = 1) -> str:
    try:
        return os.readlink(f"/proc/{pid}/fd/{fd}")
    except OSError:
        return ""


def _is_maa_picli(pid: int) -> bool:
    cmd = _cmdline(pid)
    if "MaaPiCli" in cmd:
        return True
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return False
    return "MaaPiCli" in exe


def find_maa_picli_pids() -> list[int]:
    """按祖先 / 同会话 / 同 TTY 找仍占着终端的 MaaPiCli。

    Agent 常被 systemd 收养，getppid() 不可靠；Ctrl+C 能退是因为信号打到 PiCli。
    """
    me = os.getpid()
    found: list[int] = []
    seen: set[int] = set()

    def add(pid: int) -> None:
        if pid <= 1 or pid == me or pid in seen:
            return
        if _is_maa_picli(pid):
            seen.add(pid)
            found.append(pid)

    # 1) 祖先链
    pid = os.getppid()
    for _ in range(32):
        if pid <= 1:
            break
        add(pid)
        pid = _ppid(pid)

    my_sid = _sid(me)
    my_tty = _fd_tty(me, 1) or _fd_tty(me, 0) or _fd_tty(me, 2)

    # 2) 扫 /proc：同 session 或同 tty
    try:
        proc_dirs = list(Path("/proc").iterdir())
    except OSError:
        proc_dirs = []
    for entry in proc_dirs:
        name = entry.name
        if not name.isdigit():
            continue
        pid = int(name)
        if pid == me or pid in seen:
            continue
        if not _is_maa_picli(pid):
            continue
        if my_sid and _sid(pid) == my_sid:
            add(pid)
            continue
        if my_tty and my_tty.startswith("/dev/") and (
            _fd_tty(pid, 1) == my_tty
            or _fd_tty(pid, 0) == my_tty
            or _fd_tty(pid, 2) == my_tty
        ):
            add(pid)

    return found


def terminate_parent_maa_picli() -> None:
    """结束占着 TTY 的 MaaPiCli，把提示符还给 shell（等同 Ctrl+C）。"""
    targets = find_maa_picli_pids()
    if not targets:
        # 直接打 stderr，避免 loguru enqueue + os._exit 丢日志
        sys.stderr.write("warn:未找到同会话/TTY 的 MaaPiCli，无法自动回到 shell\n")
        sys.stderr.flush()
        return

    for pid in targets:
        msg = f"info:结束 MaaPiCli pid={pid}（SIGINT），回到 shell\n"
        sys.stderr.write(msg)
        sys.stderr.flush()
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            continue

    # 给 PiCli 信号处理一点时间；仍活着再 SIGKILL
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        alive = [pid for pid in targets if Path(f"/proc/{pid}").exists()]
        if not alive:
            return
        time.sleep(0.05)
    for pid in targets:
        if not Path(f"/proc/{pid}").exists():
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_agent_tui() -> None:
    _quiet_console_logging()
    logger.info("Agent TUI 启动（控制台日志降至 ERROR，详情见 debug/custom）")
    from .app import AgentTuiApp

    AgentTuiApp().run()
