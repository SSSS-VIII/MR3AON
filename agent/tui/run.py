"""启动 / 关闭 Agent 内嵌 Textual TUI。"""

from __future__ import annotations

import os
import signal
import sys
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


def terminate_parent_maa_picli() -> None:
    """./run 是 exec MaaPiCli；只退 Agent 会停在 PiCli 会话里，需一并结束父进程。"""
    ppid = os.getppid()
    if ppid <= 1:
        return
    try:
        raw = Path(f"/proc/{ppid}/cmdline").read_bytes()
    except OSError:
        return
    cmd = raw.replace(b"\x00", b" ").decode(errors="replace")
    if "MaaPiCli" not in cmd:
        logger.warning(f"父进程不像 MaaPiCli，跳过结束: pid={ppid} cmd={cmd!r}")
        return
    logger.info(f"结束父进程 MaaPiCli pid={ppid}，回到 shell")
    try:
        os.kill(ppid, signal.SIGTERM)
    except ProcessLookupError:
        return


def run_agent_tui() -> None:
    _quiet_console_logging()
    logger.info("Agent TUI 启动（控制台日志降至 ERROR，详情见 debug/custom）")
    from .app import AgentTuiApp

    AgentTuiApp().run()
