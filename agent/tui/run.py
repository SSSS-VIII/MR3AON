"""启动 / 关闭 Agent 内嵌 Textual TUI。"""

from __future__ import annotations

import os
import sys

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


def run_agent_tui() -> None:
    _quiet_console_logging()
    logger.info("Agent TUI 启动（控制台日志降至 ERROR，详情见 debug/custom）")
    from .app import AgentTuiApp

    AgentTuiApp().run()
