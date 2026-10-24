# -*- coding: utf-8 -*-
"""防止 MaaPiCli 退出后 Agent 被 systemd 收养而泄漏。"""

from __future__ import annotations

import atexit
import ctypes
import os
import signal
import sys
import threading
import time
from pathlib import Path

from utils.logger import logger

_PR_SET_PDEATHSIG = 1
_launch_ppid: int = 0
_watchdog_started = False
_socket_id: str | None = None


def _cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode(errors="replace")


def _ppid(pid: int) -> int:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return 0
    rparen = stat.rfind(")")
    if rparen < 0:
        return 0
    fields = stat[rparen + 2 :].split()
    if len(fields) < 2:
        return 0
    try:
        return int(fields[1])
    except ValueError:
        return 0


def _pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return Path(f"/proc/{pid}").exists()


def _is_reaper_ppid(pid: int) -> bool:
    """父进程是否为 init / user systemd（孤儿收养者）。"""
    if pid <= 1:
        return True
    cmd = _cmdline(pid)
    return "systemd --user" in cmd or cmd.rstrip().endswith("systemd")


def _is_mr3a_agent(pid: int) -> bool:
    cmd = _cmdline(pid)
    if "agent/main.py" not in cmd:
        return False
    return "MR3A" in cmd or "main.py" in cmd


def install_parent_death_signal(sig: int = signal.SIGTERM) -> None:
    """Linux：父进程死后内核向本进程发信号，避免僵尸 agent。"""
    if not sys.platform.startswith("linux"):
        return
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        if libc.prctl(_PR_SET_PDEATHSIG, ctypes.c_int(sig)) != 0:
            err = ctypes.get_errno()
            logger.warning(f"prctl(PR_SET_PDEATHSIG) 失败 errno={err}")
            return
        # 父进程可能在 fork 与 prctl 之间已死
        if _is_reaper_ppid(os.getppid()):
            logger.error("启动时父进程已不在，退出以免成为孤儿 agent")
            os._exit(1)
        logger.debug(f"已安装 PR_SET_PDEATHSIG -> {sig}")
    except Exception as exc:
        logger.warning(f"无法安装 PR_SET_PDEATHSIG: {exc}")


def _exit_because_parent_gone(reason: str) -> None:
    msg = f"warn:Agent 父进程已消失（{reason}），退出以免泄漏\n"
    try:
        sys.stderr.write(msg)
        sys.stderr.flush()
    except Exception:
        pass
    _cleanup_socket_file()
    os._exit(0)


def start_parent_watchdog(interval_s: float = 2.0) -> None:
    """备用：轮询启动时的 ppid，防止 PDEATHSIG 未生效。"""
    global _watchdog_started, _launch_ppid
    if _watchdog_started:
        return
    _watchdog_started = True
    _launch_ppid = os.getppid()

    def _loop() -> None:
        while True:
            time.sleep(interval_s)
            if not _pid_alive(_launch_ppid):
                _exit_because_parent_gone(f"launch_ppid={_launch_ppid} dead")
            cur = os.getppid()
            if cur != _launch_ppid and _is_reaper_ppid(cur):
                _exit_because_parent_gone(
                    f"reparented launch={_launch_ppid} now={cur}"
                )

    threading.Thread(target=_loop, name="mr3a-parent-watch", daemon=True).start()
    logger.debug(f"父进程 watchdog 已启动 launch_ppid={_launch_ppid}")


def reap_orphan_agents() -> int:
    """杀掉已被 systemd/init 收养的其它 MR3A agent（不含自己）。"""
    me = os.getpid()
    killed = 0
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return 0

    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == me:
            continue
        if not _is_mr3a_agent(pid):
            continue
        parent = _ppid(pid)
        if not _is_reaper_ppid(parent):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
            logger.info(f"清理孤儿 agent pid={pid} ppid={parent}")
        except ProcessLookupError:
            pass
        except PermissionError:
            logger.warning(f"无权结束孤儿 agent pid={pid}")

    # 给 SIGTERM 一点时间，再扫一遍 SIGKILL
    if killed:
        time.sleep(0.4)
        for entry in Path("/proc").iterdir() if Path("/proc").exists() else []:
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid == me or not _is_mr3a_agent(pid):
                continue
            if not _is_reaper_ppid(_ppid(pid)):
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    return killed


def register_socket_cleanup(socket_id: str) -> None:
    global _socket_id
    _socket_id = socket_id
    atexit.register(_cleanup_socket_file)


def _cleanup_socket_file() -> None:
    if not _socket_id:
        return
    path = Path(f"/tmp/maafw-agent-{_socket_id}.sock")
    try:
        if path.exists() or path.is_socket():
            path.unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_stale_agent_sockets() -> int:
    """删除没有对应存活 agent 的 maafw-agent sock。"""
    live_ids: set[str] = set()
    try:
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if not _is_mr3a_agent(pid):
                continue
            cmd = _cmdline(pid)
            parts = cmd.split()
            if parts:
                live_ids.add(parts[-1].strip())
    except OSError:
        pass

    removed = 0
    for sock in Path("/tmp").glob("maafw-agent-*.sock"):
        sid = sock.name.removeprefix("maafw-agent-").removesuffix(".sock")
        if sid in live_ids:
            continue
        try:
            sock.unlink(missing_ok=True)
            removed += 1
        except OSError:
            pass
    if removed:
        logger.info(f"已删除 {removed} 个残留 agent socket")
    return removed


def guard_agent_process(socket_id: str) -> None:
    """启动时调用：装死亡信号、清孤儿、挂 watchdog、登记 sock 清理。"""
    install_parent_death_signal()
    n = reap_orphan_agents()
    if n:
        logger.info(f"启动前清理了 {n} 个孤儿 agent")
    cleanup_stale_agent_sockets()
    register_socket_cleanup(socket_id)
    start_parent_watchdog()
