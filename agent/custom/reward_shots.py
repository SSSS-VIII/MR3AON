"""奖励结算截图：按目录保存、注册给 TUI、按日常 05:00 周期清理。"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from utils.logger import logger

_DAILY_RESET_HOUR = 5
_REGISTRY_NAME = "registry.json"
# 允许中文、字母数字、_ - +（S_SS+ 等任务名）
_SAFE_DIR_RE = re.compile(r"[^\w\u4e00-\u9fff+\-]+")

_lock = threading.RLock()
# 流水线注册过的目录名（相对 reward_shots 根）
_registered: set[str] = set()
_last_prune_cycle: Optional[datetime] = None
# dir -> (last_save_ts, battle_id, path)；burst_replace 用间隔区分场次
_burst_state: dict[str, tuple[float, int, Path]] = {}
# 结算连点通常 1～3s；跨场要隔战斗，默认 10s
_DEFAULT_BURST_GAP_SEC = 10.0


def _local_now() -> datetime:
    return datetime.now().astimezone()


def daily_cycle_start(now: Optional[datetime] = None) -> datetime:
    """当前日常周期起点（今日或昨日 05:00）。"""
    from datetime import timedelta

    now = now or _local_now()
    cycle = now.replace(
        hour=_DAILY_RESET_HOUR, minute=0, second=0, microsecond=0
    )
    if cycle > now:
        cycle -= timedelta(days=1)
    return cycle


def reward_shots_root() -> Path:
    """相对进程 cwd 的 debug/reward_shots。

    DEBUG 模式 main 会 chdir 到 assets/，故实机路径是 assets/debug/reward_shots。
    """
    return Path("debug") / "reward_shots"


def sanitize_dir_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        raise ValueError("dir 不能为空")
    cleaned = _SAFE_DIR_RE.sub("_", text).strip("._")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError(f"非法目录名: {name!r}")
    return cleaned


def dir_path(name: str) -> Path:
    return reward_shots_root() / sanitize_dir_name(name)


def _registry_path() -> Path:
    return reward_shots_root() / _REGISTRY_NAME


def _load_registry_unlocked() -> None:
    path = _registry_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"reward_shots: 读取 registry 失败: {exc}")
        return
    dirs = data.get("dirs") if isinstance(data, dict) else None
    if isinstance(dirs, list):
        for item in dirs:
            if isinstance(item, str) and item.strip():
                try:
                    _registered.add(sanitize_dir_name(item))
                except ValueError:
                    continue


def _save_registry_unlocked() -> None:
    root = reward_shots_root()
    root.mkdir(parents=True, exist_ok=True)
    payload = {"dirs": sorted(_registered)}
    path = _registry_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def register_dir(name: str) -> str:
    """注册目录供 TUI 筛选；返回规范化目录名。"""
    safe = sanitize_dir_name(name)
    with _lock:
        _load_registry_unlocked()
        if safe not in _registered:
            _registered.add(safe)
            _save_registry_unlocked()
        dir_path(safe).mkdir(parents=True, exist_ok=True)
    return safe


def listed_dirs() -> list[str]:
    """已注册 + 磁盘上已有子目录。"""
    with _lock:
        _load_registry_unlocked()
        found = set(_registered)
        root = reward_shots_root()
        if root.is_dir():
            for child in root.iterdir():
                if child.is_dir():
                    try:
                        found.add(sanitize_dir_name(child.name))
                    except ValueError:
                        continue
        return sorted(found)


def prune_if_needed(now: Optional[datetime] = None) -> int:
    """删除上一日常周期之前的截图；返回删除文件数。"""
    global _last_prune_cycle
    now = now or _local_now()
    cycle = daily_cycle_start(now)
    with _lock:
        if _last_prune_cycle == cycle:
            return 0
        _last_prune_cycle = cycle
        root = reward_shots_root()
        if not root.is_dir():
            return 0
        cycle_ts = cycle.timestamp()
        removed = 0
        for path in root.rglob("*.png"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime < cycle_ts:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError as exc:
                logger.warning(f"reward_shots: 清理失败 {path}: {exc}")
        if removed:
            logger.info(
                f"reward_shots: 日常重置清理 {removed} 张 "
                f"(cycle>={cycle.isoformat(timespec='seconds')})"
            )
        return removed


def list_shots(dir_name: Optional[str] = None) -> list[Path]:
    """列出当前周期内截图，新→旧。dir_name=None 表示全部已注册/已有目录。"""
    prune_if_needed()
    roots: list[Path]
    if dir_name:
        roots = [dir_path(dir_name)]
    else:
        roots = [dir_path(name) for name in listed_dirs()]
    files: list[Path] = []
    cycle_ts = daily_cycle_start().timestamp()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("*.png"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime >= cycle_ts:
                    files.append(path)
            except OSError:
                continue
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def save_image_array(
    image: Any,
    dir_name: str,
    *,
    burst_replace: bool = False,
    burst_gap_sec: float = _DEFAULT_BURST_GAP_SEC,
) -> Optional[Path]:
    """保存 BGR/RGB ndarray 到目录；失败返回 None。

    burst_replace=True：距上次保存不足 burst_gap_sec（默认 10s）视为同场连点，
    覆盖该场 b00N.png 只留最后一张；超过则新开场次。不依赖 hit_count，任务重开也安全。
    """
    from PIL import Image

    if image is None:
        logger.warning("reward_shots: 无图像，跳过保存")
        return None
    safe = register_dir(dir_name)
    prune_if_needed()
    try:
        out_dir = dir_path(safe)
        out_dir.mkdir(parents=True, exist_ok=True)
        now = _local_now()
        now_ts = now.timestamp()
        gap = max(0.0, float(burst_gap_sec))

        with _lock:
            if burst_replace:
                prev = _burst_state.get(safe)
                if prev is not None and (now_ts - prev[0]) < gap:
                    battle_id = prev[1]
                    path = prev[2]
                else:
                    battle_id = (prev[1] + 1) if prev is not None else 1
                    # 任务重开内存清空时，跳过磁盘上已有的 b00N，避免盖掉上一趟
                    while True:
                        candidate = out_dir / f"b{battle_id:03d}.png"
                        if not candidate.exists() or (
                            prev is not None and candidate == prev[2]
                        ):
                            path = candidate
                            break
                        battle_id += 1
            else:
                battle_id = 0
                ts = now.strftime("%Y%m%d-%H%M%S-%f")[:-3]
                path = out_dir / f"{ts}.png"

        arr = image
        if getattr(arr, "ndim", 0) == 3 and arr.shape[2] == 3:
            # Maa / OpenCV: BGR → RGB
            arr = arr[:, :, ::-1]
        Image.fromarray(arr).save(path)

        if burst_replace:
            with _lock:
                _burst_state[safe] = (now_ts, battle_id, path)
            logger.info(
                f"reward_shots: 已保存 {path} (battle={battle_id}, burst_replace)"
            )
        else:
            logger.info(f"reward_shots: 已保存 {path}")
        return path
    except Exception as exc:
        logger.exception(f"reward_shots: 保存失败: {exc}")
        return None


@dataclass(frozen=True)
class GalleryState:
    dirs: tuple[str, ...]
    dir_filter: Optional[str]  # None = 全部
    paths: tuple[Path, ...]
    index: int


def gallery_snapshot(
    dir_filter: Optional[str] = None,
    index: int = 0,
) -> GalleryState:
    dirs = tuple(listed_dirs())
    paths = tuple(list_shots(dir_filter))
    if not paths:
        idx = 0
    else:
        idx = max(0, min(index, len(paths) - 1))
    return GalleryState(dirs=dirs, dir_filter=dir_filter, paths=paths, index=idx)


# 供测试重置
def _reset_for_tests() -> None:
    global _last_prune_cycle
    with _lock:
        _registered.clear()
        _last_prune_cycle = None
        _burst_state.clear()
