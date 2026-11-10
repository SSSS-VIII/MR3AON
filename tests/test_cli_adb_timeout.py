"""实际子进程验证：截图挂死会关闭管道，且不改变ADB参数或实例环境。"""
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / 'tools/maa-adb'


def test_cli_adb_preserves_arguments_environment_and_binary_output(tmp_path):
    fake = tmp_path / 'adb with spaces'
    fake.write_text('#!/usr/bin/env python3\nimport os,sys,json\n'
                    'sys.stdout.buffer.write(b"\\x89PNG\\r\\n"+json.dumps('
                    '[sys.argv[1:],os.environ["ADB_SERVER_SOCKET"]]).encode())\n')
    fake.chmod(0o755)
    args = ['-s', '192.168.242.112:5555', 'exec-out', 'screencap | gzip -1']
    result = subprocess.run([str(WRAPPER), *args], capture_output=True, timeout=5,
                            env={**os.environ, 'MR3A_REAL_ADB': str(fake),
                                 'ADB_SERVER_SOCKET': 'tcp:5039'})
    assert result.returncode == 0
    assert result.stdout.startswith(b'\x89PNG\r\n')
    assert json.loads(result.stdout[6:]) == [args, 'tcp:5039']


def test_cli_adb_blocked_read_ends_at_command_deadline(tmp_path):
    fake = tmp_path / 'blocked-adb'
    # exec keeps only the child being tested; real server is a separate daemon.
    fake.write_text('#!/bin/sh\nexec sleep 60\n')
    fake.chmod(0o755)
    started = time.monotonic()
    result = subprocess.run([str(WRAPPER), '-s', 'named-device', 'exec-out',
                             'screencap | gzip -1'], capture_output=True, timeout=26,
                            env={**os.environ, 'MR3A_REAL_ADB': str(fake)})
    assert result.returncode == 124
    assert 19 <= time.monotonic() - started < 25
