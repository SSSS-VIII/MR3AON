from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from runtime import InstanceSession
from test_named_instances import registry


def test_public_adb_requires_control_and_keeps_complete_output(registry):
    session = InstanceSession("xiaoli", registry=registry)
    with pytest.raises(RuntimeError, match="control"):
        session.adb("shell", "id")
    response = subprocess.CompletedProcess([], 7, b"\x00\xff", b"device error")
    with session.control(), patch.object(session, "_adb_result", return_value=response) as execute:
        assert session.adb("exec-in", "cat", input_data=b"hello", timeout=10) is response
        execute.assert_called_once_with("exec-in", "cat", timeout=10, input_data=b"hello")


@pytest.mark.parametrize("args", [(), ("-s", "other", "shell"), ("-P", "5037"), ("devices",), ("connect", "other"), ("kill-server",), ("forward", "tcp:1", "tcp:2"), ("shell", "bad\0arg")])
def test_public_adb_cannot_select_another_device_or_host_server(registry, args):
    session = InstanceSession("xiaoli", registry=registry)
    with session.control(), patch.object(session, "_adb_result") as execute:
        with pytest.raises(ValueError):
            session.adb(*args)
        execute.assert_not_called()


def test_public_adb_binds_the_named_server_and_target(registry):
    session = InstanceSession("xiaoli", registry=registry)
    session._serial = "192.168.241.112:5555"
    response = subprocess.CompletedProcess([], 0, b"ok", b"")
    with session.control(), patch("runtime.instances.subprocess.run", return_value=response) as execute:
        session.adb("shell", "getprop", "sys.boot_completed")
    command = execute.call_args.args[0]
    assert command[1:] == ["-P", str(session.spec.adb_port), "-s", session._serial, "shell", "getprop", "sys.boot_completed"]
    assert execute.call_args.kwargs["env"]["ANDROID_SERIAL"] == session._serial
