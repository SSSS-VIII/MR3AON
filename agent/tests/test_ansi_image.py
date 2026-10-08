from __future__ import annotations

from pathlib import Path

from PIL import Image

from tui.ansi_image import render_carousel, render_halfblock


def _solid(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (64, 36)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def test_render_halfblock_nonempty(tmp_path: Path):
    p = _solid(tmp_path / "a.png", (200, 40, 40))
    text = render_halfblock(p, max_cols=20, max_rows=6)
    assert "▀" in text
    assert "preview failed" not in text


def test_carousel_peeks_neighbors(tmp_path: Path):
    a = _solid(tmp_path / "a.png", (220, 40, 40))
    b = _solid(tmp_path / "b.png", (40, 200, 40))
    c = _solid(tmp_path / "c.png", (40, 40, 220))
    text = render_carousel(a, b, c, total_cols=40, total_rows=8, peek_cols=4)
    assert "▀" in text
    # 中间有图时不应退回 too small
    assert "(too small)" not in text
    # 无左侧邻图时仍能画
    edge = render_carousel(None, b, c, total_cols=40, total_rows=8)
    assert "▀" in edge
