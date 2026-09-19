"""本机 Waydroid / ADB 就绪检查与拉起。"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from typing import Optional

from utils.adb_device import adb_shell, adb_target, pidof_package
from utils.logger import logger

# 脚本按 16:9 横屏工作。Waydroid 物理分辨率会跟着窗口变，必须覆写成这个值。
DISPLAY_SIZE = "1280x720"


def waydroid_bin() -> str:
    return shutil.which("waydroid") or "/usr/bin/waydroid"


def waydroid_status_text(wait_sec: float = 15) -> str:
    result = subprocess.run(
        [waydroid_bin(), "status"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=wait_sec,
        check=False,
    )
    return (result.stdout or result.stderr or "").strip()


def session_running(status: Optional[str] = None) -> bool:
    text = status if status is not None else waydroid_status_text()
    return _status_value(text, "session") == "running"


def container_frozen(status: Optional[str] = None) -> bool:
    text = status if status is not None else waydroid_status_text()
    return _status_value(text, "container") == "frozen"


def _status_value(status: str, key: str) -> str:
    prefix = key.lower() + ":"
    for line in status.splitlines():
        lowered = line.lower()
        if lowered.startswith(prefix):
            return line.split(":", 1)[1].strip().lower()
    return ""


def _run_waydroid(*args: str, wait_sec: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [waydroid_bin(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=wait_sec,
        check=False,
    )


def stop_session() -> None:
    result = _run_waydroid("session", "stop", wait_sec=120)
    logger.info(
        f"waydroid session stop: code={result.returncode} "
        f"out={(result.stdout or result.stderr or '').strip()!r}"
    )


def start_session_background() -> None:
    """session start 会常驻前台，因此后台拉起后轮询 status。"""
    subprocess.Popen(
        [waydroid_bin(), "session", "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    logger.info("waydroid session start: 已后台拉起")


def show_full_ui() -> None:
    """session start 不会开窗口。要看见画面必须再 show-full-ui。"""
    result = _run_waydroid("show-full-ui", wait_sec=30)
    logger.info(
        f"waydroid show-full-ui: code={result.returncode} "
        f"out={(result.stdout or result.stderr or '').strip()!r}"
    )
    _focus_waydroid_window()


def _focus_waydroid_window() -> None:
    niri = shutil.which("niri")
    if not niri:
        return
    try:
        listed = subprocess.run(
            [niri, "msg", "-j", "windows"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        windows = json.loads(listed.stdout or "[]")
    except Exception as exc:
        logger.debug(f"查询 niri 窗口失败: {exc}")
        return
    window_id = next(
        (
            item.get("id")
            for item in windows
            if item.get("app_id") == "Waydroid" or item.get("title") == "Waydroid"
        ),
        None,
    )
    if window_id is None:
        logger.warning("show-full-ui 之后没有找到 Waydroid 窗口")
        return
    focused = subprocess.run(
        [niri, "msg", "action", "focus-window", "--id", str(window_id)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        check=False,
    )
    if focused.returncode == 0:
        logger.info(f"已把 Waydroid 窗口切到前台: id={window_id}")
    else:
        logger.warning(
            f"聚焦 Waydroid 窗口失败: code={focused.returncode} "
            f"out={(focused.stdout or focused.stderr or '').strip()!r}"
        )


def wait_session_running(deadline_sec: float = 120) -> bool:
    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        if session_running():
            return True
        time.sleep(2)
    return False


def wait_session_stopped(deadline_sec: float = 60) -> bool:
    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        if not session_running():
            return True
        time.sleep(1)
    return False


def set_display_size(size: str = DISPLAY_SIZE) -> None:
    """把 Android 逻辑分辨率设成脚本能识别的 16:9。"""
    adb, serial = adb_target()
    current = adb_shell(adb, serial, "wm", "size", wait_sec=10)
    if f"Override size: {size}" in current:
        logger.info(f"wm size 已是 {size}")
        return
    adb_shell(adb, serial, "wm", "size", size, wait_sec=10)
    confirmed = adb_shell(adb, serial, "wm", "size", wait_sec=10)
    if f"Override size: {size}" not in confirmed:
        raise RuntimeError(f"wm size 设置失败: {confirmed!r}")
    logger.info(f"已设置 wm size {size}")


def connect_adb() -> None:
    result = _run_waydroid("adb", "connect", wait_sec=60)
    logger.info(
        f"waydroid adb connect: code={result.returncode} "
        f"out={(result.stdout or result.stderr or '').strip()!r}"
    )


def wait_adb_device(deadline_sec: float = 90) -> bool:
    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        try:
            adb_target()
            return True
        except Exception:
            try:
                connect_adb()
            except Exception as exc:
                logger.debug(f"adb connect 重试: {exc}")
            time.sleep(2)
    return False


def wait_android_ready(deadline_sec: float = 90) -> bool:
    """ADB 出现后还要等系统启动完成，否则马上 StartApp 会失败。"""
    from utils.adb_device import adb_shell

    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        try:
            adb, serial = adb_target()
            booted = adb_shell(adb, serial, "getprop", "sys.boot_completed", wait_sec=8).strip()
            if booted == "1":
                logger.info("Android sys.boot_completed=1")
                return True
        except Exception as exc:
            logger.debug(f"等待 Android 启动: {exc}")
        time.sleep(2)
    return False


def ensure_waydroid_and_adb(
    *,
    start_if_needed: bool = True,
    deadline_sec: float = 120,
) -> None:
    """确保 Session 在跑、容器未冻结，且 ADB 和 Android 都已就绪。"""
    status = waydroid_status_text()
    if container_frozen(status):
        logger.warning("Waydroid container 已冻结，重启 session")
        try:
            stop_session()
        except Exception as exc:
            logger.warning(f"session stop 异常，继续等待停止: {exc}")
        wait_session_stopped(deadline_sec=60)
        status = waydroid_status_text()

    if session_running(status) and not container_frozen(status):
        logger.info("Waydroid session 已在运行")
    elif start_if_needed:
        logger.info("Waydroid session 未运行，尝试拉起")
        start_session_background()
        if not wait_session_running(deadline_sec=deadline_sec):
            raise RuntimeError("等待 Waydroid session 进入 RUNNING 超时")
        if container_frozen():
            raise RuntimeError("Waydroid session 已起来，但 container 仍是 FROZEN")
    else:
        raise RuntimeError("Waydroid session 未运行")

    connect_adb()
    if not wait_adb_device(deadline_sec=min(90.0, deadline_sec)):
        raise RuntimeError("等待 ADB 设备就绪超时")
    if not wait_android_ready(deadline_sec=min(90.0, deadline_sec)):
        raise RuntimeError("等待 Android 启动完成超时")
    set_display_size()
    show_full_ui()


def restart_waydroid_session(deadline_sec: float = 180) -> None:
    """停止并重新拉起 session，再恢复 ADB。不需要 root container restart。"""
    logger.warning("正在重启 Waydroid session")
    try:
        stop_session()
    except Exception as exc:
        logger.warning(f"session stop 异常，继续等待停止: {exc}")
    wait_session_stopped(deadline_sec=60)
    time.sleep(2)
    start_session_background()
    if not wait_session_running(deadline_sec=deadline_sec):
        raise RuntimeError("重启后等待 Waydroid session RUNNING 超时")
    connect_adb()
    if not wait_adb_device(deadline_sec=90):
        raise RuntimeError("重启后等待 ADB 设备就绪超时")
    if not wait_android_ready(deadline_sec=90):
        raise RuntimeError("重启后等待 Android 启动完成超时")
    set_display_size()
    show_full_ui()


__all__ = [
    "connect_adb",
    "ensure_waydroid_and_adb",
    "pidof_package",
    "restart_waydroid_session",
    "session_running",
    "waydroid_status_text",
]
