"""安全接入 textual-image（Kitty TGP），避免终端探测把 Agent 打崩。"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Optional, Type

logger = logging.getLogger(__name__)

_TermImage: Optional[Type[Any]] = None
_load_error: Optional[str] = None


def _install_probe_guard() -> None:
    """textual-image 在 winsz 列/行为 0 时会 ZeroDivisionError，且未捕获。"""
    os.environ.setdefault("TEXTUAL_CELL_WIDTH", "10")
    os.environ.setdefault("TEXTUAL_CELL_HEIGHT", "20")

    import textual_image._terminal as term

    if getattr(term.probe_terminal, "_mr3a_guarded", False):
        return

    def probe_terminal() -> Any:
        if hasattr(probe_terminal, "_result"):
            return getattr(probe_terminal, "_result")

        cell_w = int(os.environ.get("TEXTUAL_CELL_WIDTH", "10") or "10")
        cell_h = int(os.environ.get("TEXTUAL_CELL_HEIGHT", "20") or "20")
        # 有 Kitty 窗口时直接认定 TGP，避免再往 stdin 塞探测序列
        prefer_tgp = bool(os.environ.get("KITTY_WINDOW_ID"))

        width, height = max(1, cell_w), max(1, cell_h)
        sixel = False
        tgp = prefer_tgp

        stdout = sys.__stdout__
        if stdout and stdout.isatty() and not prefer_tgp:
            try:
                rows, columns, screen_width, screen_height = term.get_tiocgwinsz()
                if columns > 0 and rows > 0 and screen_width > 0 and screen_height > 0:
                    width = max(1, int(screen_width / columns))
                    height = max(1, int(screen_height / rows))
            except OSError:
                pass
            try:
                with term.capture_until_primary_da(term._PROBE_TIMEOUT) as response:
                    stdout.write(term._tgp_support_query())
                    stdout.write("\x1b[c")
                    stdout.flush()
                sixel, tgp_detected, _, _ = term._parse_probe_response(
                    response.sequence
                )
                if tgp_detected:
                    tgp = True
            except Exception as exc:
                logger.debug("terminal graphics probe failed: %s", exc)

        caps = term.TerminalCapabilities(
            term.CellSize(width, height), sixel=sixel, tgp=tgp
        )
        setattr(probe_terminal, "_result", caps)
        return caps

    probe_terminal._mr3a_guarded = True  # type: ignore[attr-defined]
    term.probe_terminal = probe_terminal  # type: ignore[assignment]
    term.get_cell_size = lambda: probe_terminal().cell_size  # type: ignore[assignment]


def get_term_image_class() -> Optional[Type[Any]]:
    """仅 Kitty TGP 高清；非 Kitty / 加载失败返回 None（不显示任何预览）。"""
    global _TermImage, _load_error
    if _TermImage is not None:
        return _TermImage
    if _load_error is not None:
        return None
    if not os.environ.get("KITTY_WINDOW_ID"):
        _load_error = "非 Kitty 终端（无 KITTY_WINDOW_ID）"
        logger.warning("奖励截图高清预览不可用: %s", _load_error)
        return None
    try:
        _install_probe_guard()
        from textual_image.widget import TGPImage

        _TermImage = TGPImage
        return _TermImage
    except Exception as exc:
        _load_error = f"{type(exc).__name__}: {exc}"
        logger.warning("奖励截图高清预览不可用: %s", _load_error)
        return None


def term_image_unavailable_reason() -> Optional[str]:
    get_term_image_class()
    return _load_error
