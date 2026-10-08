from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from custom import reward_shots as rs


def test_save_register_list_and_prune(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rs._reset_for_tests()

    # 固定「现在」为 10:00，周期起点今日 05:00
    tz = timezone(timedelta(hours=8))
    now = datetime(2026, 10, 8, 10, 0, 0, tzinfo=tz)
    monkeypatch.setattr(rs, "_local_now", lambda: now)

    img = np.zeros((8, 8, 3), dtype=np.uint8)
    img[:, :] = (0, 0, 255)  # BGR 红
    path = rs.save_image_array(img, "每日悬赏")
    assert path is not None
    assert path.is_file()
    assert "每日悬赏" in rs.listed_dirs()

    shots = rs.list_shots("每日悬赏")
    assert len(shots) == 1
    assert shots[0] == path

    # 伪造过期文件
    old = rs.dir_path("每日悬赏") / "old.png"
    old.write_bytes(path.read_bytes())
    old_mtime = (now - timedelta(days=2)).timestamp()
    import os

    os.utime(old, (old_mtime, old_mtime))

    rs._reset_for_tests()  # 清 prune 缓存
    monkeypatch.setattr(rs, "_local_now", lambda: now)
    removed = rs.prune_if_needed(now)
    assert removed >= 1
    assert not old.exists()
    assert path.exists()


def test_sanitize_rejects_empty():
    try:
        rs.sanitize_dir_name("   ")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_sanitize_keeps_plus():
    assert rs.sanitize_dir_name("S_SS+") == "S_SS+"
