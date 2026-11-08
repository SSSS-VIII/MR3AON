#!/usr/bin/env python3
"""Keep the arena's nested compositor alive and record its display endpoints."""
import json
import os
from pathlib import Path
import signal

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "debug/arena-client/gameonly/nested-display.json"


def compositor_pid(parent=None, proc=Path('/proc')):
    """gamescope inserts gamescopereaper between itself and its child."""
    parent = os.getppid() if parent is None else parent
    for _ in range(8):
        directory = proc / str(parent)
        args = (directory / 'cmdline').read_bytes().split(b'\0')
        if (Path(os.fsdecode(args[0])).name == 'gamescope'
                and str(ROOT / 'tools/arena_display.py').encode() in args):
            return parent
        status = (directory / 'status').read_text().splitlines()
        parent = int(next(line.split()[1] for line in status if line.startswith('PPid:')))
        if parent <= 1:
            break
    raise RuntimeError('Cannot identify this arena compositor in the parent chain')


def main():
    RECORD.parent.mkdir(parents=True, exist_ok=True)
    data = {key: os.environ.get(key) for key in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_RUNTIME_DIR")}
    data["gamescope_pid"] = compositor_pid()
    temporary = RECORD.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2))
    temporary.replace(RECORD)
    while True:
        signal.pause()


if __name__ == "__main__":
    main()
