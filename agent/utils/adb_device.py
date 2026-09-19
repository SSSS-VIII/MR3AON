"""ADB device helpers for Agent custom actions/recognitions."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional


def adb_target() -> tuple[str, str]:
    adb = shutil.which("adb") or "/usr/bin/adb"
    result = subprocess.run(
        [adb, "devices"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"无法执行 adb devices: {result.stderr.strip()}")

    devices: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "device":
            devices.append(fields[0])
    if len(devices) != 1:
        raise RuntimeError(f"需要恰好一个 ADB 设备，当前发现: {devices!r}")
    return adb, devices[0]


def adb_shell(adb: str, serial: str, *args: str, wait_sec: float = 20) -> str:
    result = subprocess.run(
        [adb, "-s", serial, "shell", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=wait_sec,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"ADB shell failed: {' '.join(args)}; output={output!r}")
    return output


def pidof_package(package: str, wait_sec: float = 5) -> Optional[str]:
    """Return main pid for package, or None if not running."""
    if not package:
        return None
    try:
        adb, serial = adb_target()
    except Exception:
        return None

    result = subprocess.run(
        [adb, "-s", serial, "shell", "pidof", package],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=wait_sec,
        check=False,
    )
    output = (result.stdout or "").strip()
    if result.returncode != 0 or not output:
        return None
    return output.split()[0]
