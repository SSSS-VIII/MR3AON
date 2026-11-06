"""Opt-in process/terminal cleanup using main's device with no game input."""

import fcntl
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import struct
import termios
import time

import pytest

from runtime import InstanceSession

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.environ.get("MR3A_EXIT_LIVE") != "1", reason="需显式选择主设备，只运行无点击夹具")


def _owned_processes(work):
    marker = f"MR3A_WORK_ROOT={work}".encode()
    found = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if marker in (proc / "environ").read_bytes().split(b"\0"):
                found.append(int(proc.name))
        except OSError:
            pass
    return found


@pytest.mark.parametrize("mode", ["headless", "tui", "early", "quit"])
def test_real_agent_restores_terminal_and_reaps_children(tmp_path, mode):
    session = InstanceSession("main")
    serial = session._address()
    work = tmp_path / mode
    (work / "resource/pipeline").mkdir(parents=True)
    (work / "config").mkdir()
    delay = 15000 if mode == "quit" else (0 if mode == "early" else 1000)
    pipeline = {"ExitEntry": {"action": "DoNothing", "post_delay": delay, "next": ["ExitStop"]}, "ExitStop": {"action": "StopTask"}}
    (work / "resource/pipeline/exit.json").write_text(json.dumps(pipeline))
    interface = {
        "interface_version": 2, "name": "ExitCheck", "version": "test",
        "controller": [{"name": "ADB", "type": "Adb"}],
        "resource": [{"name": "exit", "path": ["./resource"]}],
        "task": [{"name": "ExitCheck", "entry": "ExitEntry"}],
        "agent": {"child_exec": str(ROOT / ".venv/bin/python"), "child_args": ["-u", str(ROOT / "agent/main.py")]},
    }
    (work / "interface.json").write_text(json.dumps(interface))
    config = {"controller": {"name": "ADB"}, "resource": "exit", "adb": {
        "name": serial + "-/usr/bin/adb", "adb_path": "/usr/bin/adb", "address": serial,
    }, "task": [{"name": "ExitCheck", "option": []}]}
    (work / "config/maa_pi_config.json").write_text(json.dumps(config))
    (work / "config/maa_option.json").write_text('{"logging":true,"stdout_level":0}')
    (work / "config/pip_config.json").write_text('{"enable_pip_install":false}')
    env = session.spec.environment(serial)
    env.update(MR3A_WORK_ROOT=str(work), MR3A_TUI="0" if mode == "headless" else "1", TERM="xterm-256color")
    env.pop("KITTY_WINDOW_ID", None)
    wrapper = "import os,sys;os.environ['MR3A_PICLI_PID']=str(os.getpid());os.execv(sys.argv[1],sys.argv[1:])"
    master, slave = pty.openpty()
    before = termios.tcgetattr(slave)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 90, 0, 0))
    output = bytearray()
    sent_quit = False
    with session.control():
        process = subprocess.Popen([
            str(ROOT / ".venv/bin/python"), "-c", wrapper, str(ROOT / "deps/bin/MaaPiCli"),
            "--user-dir", str(work), "--resource-dir", str(work), "-d",
        ], cwd=work, env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        try:
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.05)[0]:
                    output.extend(os.read(master, 65536))
                log_files = list((work / "debug/custom").glob("*.log"))
                started = any("Agent 调度已提交" in path.read_text() for path in log_files)
                if mode == "quit" and not sent_quit and started and b"\x1b[?1049h" in output:
                    os.write(master, b"q")
                    sent_quit = True
                if process.poll() is not None:
                    while select.select([master], [], [], 0)[0]:
                        output.extend(os.read(master, 65536))
                    break
            assert process.poll() is not None, f"实例退出超时，日志位于 {work}"
            assert process.returncode == 0
            if mode != "headless":
                assert b"\x1b[?1049l" in output, "未退出备用屏"
                assert termios.tcgetattr(slave) == before, "终端输入模式未恢复"
            assert b"leaked semaphore" not in output, "Python 资源队列被强制中断"
            assert any("AgentServer关闭" in path.read_text() for path in (work / "debug/custom").glob("*.log")), "Agent 未走正常收尾"
            deadline = time.monotonic() + 3
            while _owned_processes(work) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not _owned_processes(work), "遗留实例子进程"
        finally:
            (work / "console.log").write_bytes(output)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for pid in _owned_processes(work):
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass
            os.close(master)
            os.close(slave)
