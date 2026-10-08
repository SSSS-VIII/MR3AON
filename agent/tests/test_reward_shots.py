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


def test_burst_replace_keeps_last_within_gap(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rs._reset_for_tests()

    tz = timezone(timedelta(hours=8))
    clock = {"t": datetime(2026, 10, 9, 7, 0, 0, tzinfo=tz)}
    monkeypatch.setattr(rs, "_local_now", lambda: clock["t"])

    def paint(v: int):
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        img[:, :] = (v, 0, 0)
        return img

    p1 = rs.save_image_array(paint(1), "每日悬赏", burst_replace=True, burst_gap_sec=10)
    assert p1 is not None and p1.name == "b001.png"
    clock["t"] += timedelta(seconds=2)
    p2 = rs.save_image_array(paint(2), "每日悬赏", burst_replace=True, burst_gap_sec=10)
    assert p2 == p1
    assert list(rs.dir_path("每日悬赏").glob("*.png")) == [p1]
    from PIL import Image as PILImage

    last = np.array(PILImage.open(p1))
    assert int(last[0, 0, 2]) == 2  # BGR(2,0,0) → RGB

    clock["t"] += timedelta(seconds=11)
    p3 = rs.save_image_array(paint(3), "每日悬赏", burst_replace=True, burst_gap_sec=10)
    assert p3 is not None and p3.name == "b002.png"
    assert [s.name for s in sorted(rs.dir_path("每日悬赏").glob("*.png"))] == [
        "b001.png",
        "b002.png",
    ]

    # 模拟任务重开：内存清空后不应覆盖磁盘上已有 b001
    rs._reset_for_tests()
    monkeypatch.setattr(rs, "_local_now", lambda: clock["t"])
    p4 = rs.save_image_array(paint(4), "每日悬赏", burst_replace=True, burst_gap_sec=10)
    assert p4 is not None and p4.name == "b003.png"
    assert np.array(PILImage.open(p1))[0, 0, 2] == 2
