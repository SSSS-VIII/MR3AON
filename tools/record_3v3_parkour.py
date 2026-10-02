#!/usr/bin/env python3
"""3v3 跑图按键录制（极简）。

  s → 下翻 (200, 620)
  k → 跳跃 (1100, 620)
  q → 结束，写出相对间隔序列

不识图、不校准起始偏移；只保留按键相对顺序与间隔，主偏移你后调。

写出给 Agent 的 delay 已减去 ``interruptible`` 里 ClickDelayState 的
``+60ms`` 修正：人手按键间隔若原样粘贴，实跑会每步再 +60，整条相对录制
基线线性变慢。日志里的 gap= 仍是原始间隔；``.py`` 里是 Agent 可直接粘贴值。
"""

from __future__ import annotations

import select
import subprocess
import sys
import termios
import time
import tty
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JUMP = (1100, 620)
DOWN = (200, 620)
# 与 agent/custom/interruptible.py 中 _CLICK_DELAY_CORRECTION_MS 保持一致。
AGENT_DELAY_CORRECTION_MS = 60
KEYS = {
    "s": ("下翻", DOWN),
    "S": ("下翻", DOWN),
    "k": ("跳跃", JUMP),
    "K": ("跳跃", JUMP),
}


def adb_tap(x: int, y: int) -> None:
    r = subprocess.run(
        ["adb", "shell", "input", "tap", str(x), str(y)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "adb tap failed").strip())


def read_key(timeout: float = 0.05) -> str | None:
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    ch = sys.stdin.read(1)
    if ch == "\x03":
        return "q"
    return ch


def main() -> int:
    out_dir = ROOT / "debug" / "3v3-record"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = out_dir / f"{stamp}.log"
    py_path = out_dir / f"{stamp}.py"

    events: list[tuple[str, int, int, float]] = []  # name,x,y,monotonic

    def log(msg: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    # 确认 adb 还能 tap
    try:
        subprocess.run(
            ["adb", "get-state"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except Exception as exc:
        print(f"adb 不可用: {exc}", file=sys.stderr)
        return 1

    log(f"log={log_path}")
    log(f"out={py_path}")
    log("s=下翻 k=跳跃 q=结束；回车后开始")
    try:
        input()
    except EOFError:
        pass

    log("录制中…")
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            ch = read_key()
            if ch is None:
                continue
            if ch in ("q", "Q"):
                break
            mapped = KEYS.get(ch)
            if not mapped:
                continue
            name, (x, y) = mapped
            t = time.monotonic()
            try:
                adb_tap(x, y)
            except Exception as exc:
                log(f"tap 失败 {name}: {exc}")
                continue
            events.append((name, x, y, t))
            gap = 0 if len(events) == 1 else int(round((t - events[-2][3]) * 1000))
            log(f"#{len(events)} {name} ({x},{y}) gap={gap}ms")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    lines = [
        "        # record-3v3-parkour → Agent 粘贴用",
        (
            "        # 原始按键间隔已减去 ClickDelayState 的 +60ms 修正"
            f"（AGENT_DELAY_CORRECTION_MS={AGENT_DELAY_CORRECTION_MS}）；"
        ),
        "        # 否则实跑每步再 +60，相对录制基线线性变慢。主偏移自行改首段。",
        "        # 勿对下列 delay 再减一遍 60。click(200,620)=下翻  click(1100,620)=跳跃",
    ]
    for i, (name, x, y, t) in enumerate(events):
        if i + 1 < len(events):
            raw_delay = max(0, int(round((events[i + 1][3] - t) * 1000)))
            delay = max(0, raw_delay - AGENT_DELAY_CORRECTION_MS)
        else:
            raw_delay = 0
            delay = 0
        lines.append(
            f"        click({x}, {y}, {delay})  # {name}"
            f"  raw_gap={raw_delay}ms"
        )
    text = "\n".join(lines) + "\n"
    py_path.write_text(text, encoding="utf-8")
    log(f"共 {len(events)} 次 → {py_path}")
    log(
        f"已导出 Agent delay=raw_gap-{AGENT_DELAY_CORRECTION_MS}；"
        "勿再对粘贴结果重复减 60"
    )
    print()
    print(text)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n中断", file=sys.stderr)
        raise SystemExit(130)
