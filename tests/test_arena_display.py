from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from arena_display import ROOT, compositor_pid


def process(proc, pid, parent, *args):
    directory = proc / str(pid)
    directory.mkdir()
    (directory / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in args) + b'\0')
    (directory / 'status').write_text(f'Name: test\nPPid:\t{parent}\n')


def test_finds_arena_compositor_through_reaper(tmp_path):
    script = str(ROOT / 'tools/arena_display.py')
    process(tmp_path, 30, 20, 'gamescopereaper', '--', 'python', script)
    process(tmp_path, 20, 1, '/usr/bin/gamescope', '--', 'python', script)
    assert compositor_pid(30, tmp_path) == 20


def test_rejects_other_compositor_in_parent_chain(tmp_path):
    process(tmp_path, 30, 1, 'gamescope', '--', 'unrelated-game')
    with pytest.raises(RuntimeError, match='this arena'):
        compositor_pid(30, tmp_path)
