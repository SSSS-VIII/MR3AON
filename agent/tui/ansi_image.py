"""把 PNG 缩成 Textual markup 半块字符预览（上下两像素 → ▀）。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image

_CELL = "[#{r1:02x}{g1:02x}{b1:02x} on #{r2:02x}{g2:02x}{b2:02x}]▀[/]"


def _fit_rgb(path: Path, max_cols: int, max_rows: int) -> Image.Image:
    """缩放到不超过 max_cols × (max_rows*2)，奇高补黑行。"""
    with Image.open(path) as im:
        im = im.convert("RGB")
        target_h = max(2, max_rows * 2)
        im.thumbnail((max_cols, target_h), Image.Resampling.BILINEAR)
        w, h = im.size
        if h % 2:
            canvas = Image.new("RGB", (w, h + 1), (0, 0, 0))
            canvas.paste(im, (0, 0))
            im = canvas
        return im


def _image_to_lines(im: Image.Image) -> list[str]:
    px = im.load()
    w, h = im.size
    lines: list[str] = []
    for y in range(0, h, 2):
        parts: list[str] = []
        for x in range(w):
            r1, g1, b1 = px[x, y]
            r2, g2, b2 = px[x, y + 1]
            parts.append(_CELL.format(r1=r1, g1=g1, b1=b1, r2=r2, g2=g2, b2=b2))
        lines.append("".join(parts))
    return lines


def _blank_lines(cols: int, rows: int) -> list[str]:
    if cols <= 0 or rows <= 0:
        return []
    cell = "[#1a1b26 on #1a1b26]▀[/]"
    line = cell * cols
    return [line] * rows


def _dim_edge_lines(cols: int, rows: int) -> list[str]:
    """无邻图时的占位边条（比空白略亮一点）。"""
    if cols <= 0 or rows <= 0:
        return []
    cell = "[#2a2e3f on #1a1b26]▀[/]"
    line = cell * cols
    return [line] * rows


def _pad_or_trim_rows(lines: list[str], rows: int, cols: int) -> list[str]:
    blank = _blank_lines(cols, 1)[0] if cols > 0 else ""
    if len(lines) >= rows:
        return lines[:rows]
    return lines + [blank] * (rows - len(lines))


def render_halfblock(
    path: Path,
    *,
    max_cols: int = 48,
    max_rows: int = 14,
) -> str:
    """返回 Textual markup；失败时返回简短错误说明。"""
    lines = render_halfblock_lines(path, max_cols=max_cols, max_rows=max_rows)
    if not lines:
        return "[dim](empty)[/]"
    return "\n".join(lines)


def _pad_width(im: Image.Image, target_w: int, *, align: str = "center") -> Image.Image:
    w, h = im.size
    if w >= target_w:
        return im
    canvas = Image.new("RGB", (target_w, h), (15, 15, 20))
    if align == "left":
        x0 = 0
    elif align == "right":
        x0 = target_w - w
    else:
        x0 = (target_w - w) // 2
    canvas.paste(im, (x0, 0))
    return canvas


def render_halfblock_lines(
    path: Path,
    *,
    max_cols: int,
    max_rows: int,
    crop: str = "full",
    crop_cols: int = 0,
    pad_to_cols: Optional[int] = None,
) -> list[str]:
    """半块行列表。crop=left/right 时从 fit 后图像取边缘，不足则黑边补到 crop_cols。"""
    if max_cols < 1 or max_rows < 1:
        return []
    try:
        im = _fit_rgb(path, max_cols, max_rows)
        w, h = im.size
        if crop in ("left", "right") and crop_cols > 0:
            take = min(crop_cols, w)
            if take <= 0:
                return []
            if crop == "left":
                strip = im.crop((0, 0, take, h))
            else:
                strip = im.crop((w - take, 0, w, h))
            if take < crop_cols:
                canvas = Image.new("RGB", (crop_cols, h), (26, 27, 38))
                x0 = 0 if crop == "left" else crop_cols - take
                canvas.paste(strip, (x0, 0))
                im = canvas
            else:
                im = strip
        elif pad_to_cols and im.size[0] < pad_to_cols:
            im = _pad_width(im, pad_to_cols, align="center")
        lines = _image_to_lines(im)
        return lines if lines else []
    except Exception:
        return []


def render_carousel(
    prev: Optional[Path],
    current: Path,
    nxt: Optional[Path],
    *,
    total_cols: int,
    total_rows: int,
    peek_cols: int = 4,
    gap_cols: int = 1,
) -> str:
    """主图居中，左右露出邻图边缘；无邻图时该侧为暗边条。"""
    if total_cols < 12 or total_rows < 2:
        return "[dim](too small)[/]"
    peek = max(2, min(peek_cols, 6))
    gap = max(0, gap_cols)
    main_cols = total_cols - 2 * peek - 2 * gap
    if main_cols < 8:
        # 太窄就只画主图
        return render_halfblock(current, max_cols=total_cols, max_rows=total_rows)

    try:
        main_lines = render_halfblock_lines(
            current,
            max_cols=main_cols,
            max_rows=total_rows,
            pad_to_cols=main_cols,
        )
        if not main_lines:
            return "[dim](empty)[/]"
        # 邻图与主图同 scale：先按 main_cols fit，再取边缘
        if prev is not None:
            left_lines = render_halfblock_lines(
                prev,
                max_cols=main_cols,
                max_rows=total_rows,
                crop="right",
                crop_cols=peek,
            )
            if not left_lines:
                left_lines = _dim_edge_lines(peek, total_rows)
        else:
            left_lines = _dim_edge_lines(peek, total_rows)
        if nxt is not None:
            right_lines = render_halfblock_lines(
                nxt,
                max_cols=main_cols,
                max_rows=total_rows,
                crop="left",
                crop_cols=peek,
            )
            if not right_lines:
                right_lines = _dim_edge_lines(peek, total_rows)
        else:
            right_lines = _dim_edge_lines(peek, total_rows)

        rows = min(
            max(len(main_lines), len(left_lines), len(right_lines), 1),
            total_rows,
        )
        left_lines = _pad_or_trim_rows(left_lines, rows, peek)
        main_lines = _pad_or_trim_rows(main_lines, rows, main_cols)
        right_lines = _pad_or_trim_rows(right_lines, rows, peek)
        gap_line = ("[#0f0f14 on #0f0f14]▀[/]" * gap) if gap else ""

        out: list[str] = []
        for i in range(rows):
            out.append(
                f"{left_lines[i]}{gap_line}{main_lines[i]}{gap_line}{right_lines[i]}"
            )
        return "\n".join(out)
    except Exception as exc:
        return f"[dim]preview failed: {exc}[/]"


def probe_image(path: Optional[Path]) -> str:
    if path is None or not path.is_file():
        return "[dim]no shot[/]"
    return render_halfblock(path)
