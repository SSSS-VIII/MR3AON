"""Opt-in read-only device smoke: MR3A_LIVE_INSTANCES=main,small pytest ..."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from runtime import InstanceSession

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not os.environ.get("MR3A_LIVE_INSTANCES"), reason="需显式指定已有设备，仅截图不操作游戏")
def test_parallel_agents_write_only_to_their_runtime_directories(tmp_path):
    jobs = []
    try:
        for name in os.environ["MR3A_LIVE_INSTANCES"].split(","):
            session = InstanceSession(name)
            serial = session._address()
            work = tmp_path / name
            (work / "resource/pipeline").mkdir(parents=True)
            (work / "config").mkdir()
            pipeline = {
                "SmokeEntry": {"recognition": "DirectHit", "action": {"type": "Custom", "param": {
                    "custom_action": "SaveRewardScreenshot", "custom_action_param": {"dir": "隔离验证", "fresh_capture": True},
                }}, "post_delay": 1000, "next": ["SmokeStop"]},
                "SmokeStop": {"action": "StopTask"},
            }
            (work / "resource/pipeline/smoke.json").write_text(json.dumps(pipeline))
            interface = {
                "interface_version": 2, "name": "NamedSmoke", "version": "test",
                "controller": [{"name": "ADB", "type": "Adb"}],
                "resource": [{"name": "smoke", "path": ["./resource"]}],
                "task": [{"name": "Smoke", "entry": "SmokeEntry"}],
                "agent": {"child_exec": str(ROOT / ".venv/bin/python"), "child_args": ["-u", str(ROOT / "agent/main.py")]},
            }
            (work / "interface.json").write_text(json.dumps(interface))
            config = {"controller": {"name": "ADB"}, "resource": "smoke", "adb": {
                "name": serial + "-/usr/bin/adb", "adb_path": "/usr/bin/adb", "address": serial,
            }, "task": [{"name": "Smoke", "option": []}]}
            (work / "config/maa_pi_config.json").write_text(json.dumps(config))
            (work / "config/maa_option.json").write_text('{"logging":true,"stdout_level":0}')
            (work / "config/pip_config.json").write_text('{"enable_pip_install":false}')
            env = session.spec.environment(serial)
            env.update(MR3A_WORK_ROOT=str(work), MR3A_TUI="0")
            log = (work / "console.log").open("wb")
            process = subprocess.Popen([
                str(ROOT / "deps/bin/MaaPiCli"), "--user-dir", str(work), "--resource-dir", str(work), "-d",
            ], env=env, cwd=work, stdout=log, stderr=subprocess.STDOUT)
            jobs.append((work, process, log))
        for work, process, _ in jobs:
            assert process.wait(timeout=45) == 0
            assert list((work / "debug/reward_shots/隔离验证").glob("*.png"))
            assert list((work / "debug/custom").glob("*.log"))
            assert (work / "config/agent_task_state.json").is_file()
            assert (work / "debug/maafw.log").is_file()
    finally:
        for _, process, log in jobs:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            log.close()
