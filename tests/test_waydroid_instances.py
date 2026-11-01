from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("waydroid_instance", ROOT / "tools/waydroid_instance.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Instance = module.Instance


def test_instances_have_distinct_host_resources():
    instances = [Instance(slot) for slot in range(1, 15)]
    for attribute in ("work", "bridge", "subnet", "binderfs", "container_bus", "session_bus", "adb_port"):
        assert len({getattr(instance, attribute) for instance in instances}) == 14
    assert all(len(instance.bridge) < 16 for instance in instances)
    assert all(instance.adb_port != 5037 for instance in instances)
    assert all(instance.subnet != "192.168.240" for instance in instances)


@pytest.mark.parametrize("slot", [-1, 15, 999])
def test_invalid_slot_is_rejected(slot):
    with pytest.raises(ValueError):
        Instance(slot)


def test_default_slot_adopts_existing_environment_unchanged():
    instance = Instance(0)
    source = '"/var/lib/waydroid" "id.waydro.Container" "waydroid0"'
    assert instance.work == Path("/var/lib/waydroid")
    assert instance.adb_port == 5037
    assert instance.container_bus == "id.waydro.Container"
    assert instance.adapt_source(source) == source
    assert instance.network_script(source) == source


def test_bus_names_are_isolated_without_changing_dbus_interfaces():
    source = '''
name = "id.waydro.Container"
session = 'id.waydro.Session'
interface = "id.waydro.ContainerManager"
root = "/var/lib/waydroid/rootfs"
binder = '/dev/binderfs/binder-control'
lease = "/var/lib/misc/dnsmasq.waydroid0.leases"
'''
    result = Instance(1).adapt_source(source)
    assert '"id.waydro.Container.mr3a1"' in result
    assert "'id.waydro.Session.mr3a1'" in result
    assert '"id.waydro.ContainerManager"' in result
    assert "/var/lib/waydroid-mr3a1/rootfs" in result
    assert "/dev/binderfs-mr3a1/binder-control" in result
    assert "dnsmasq.wdmr3a1.leases" in result
    compile(result, "adapted", "exec")


def test_network_start_and_stop_never_reference_main_nftables():
    # Same command forms used in the packaged start_nftables/stop_nftables.
    source = '''#!/bin/sh
varrun="/run/waydroid-lxc"
vnic=waydroid0
work=/var/lib/waydroid
LXC_ADDR="192.168.240.1"
rules="add table inet lxc;
flush table inet lxc;
add chain inet lxc input;
delete table ip lxc;"
net_link_key="lxc.net.0.link"
'''
    result = Instance(2).network_script(source)
    assert "/run/waydroid-mr3a2-lxc" in result
    assert "192.168.242.1" in result
    assert "delete table ip wd_mr3a2" in result
    assert "flush table inet wd_mr3a2" in result
    assert "lxc.net.0.link" in result
    assert "table inet lxc" not in result
    assert "table ip lxc" not in result
    assert "waydroid0" not in result
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh") as script:
        script.write(result)
        script.flush()
        subprocess.run(["bash", "-n", script.name], check=True)


def test_cli_help_never_loads_or_writes_system_waydroid():
    result = subprocess.run(
        ["/usr/bin/python3", str(ROOT / "tools/waydroid_instance.py"), "--help"],
        capture_output=True, text=True, check=True,
    )
    assert "--slot" in result.stdout
    assert "authorize-adb" in result.stdout


@pytest.mark.parametrize("slot", [0, 1])
def test_full_stop_targets_only_own_units_and_adb(slot):
    with patch.object(module.os, "geteuid", return_value=1000), patch.object(module.Path, "exists", return_value=False), patch.object(module.subprocess, "check_output", return_value="loaded\n"), patch.object(module.subprocess, "run") as run:
        module.manage(Instance(slot), "stop")
    commands = [call.args[0] for call in run.call_args_list]
    system_unit = f"mr3a-waydroid-{slot}" if slot else "waydroid-container"
    assert ["sudo", "-n", "systemctl", "stop", system_unit] in commands
    assert ["systemctl", "--user", "stop", f"mr3a-waydroid-session-{slot}"] in commands
    assert commands[0][3] == Instance(slot).session_bus
    adb_commands = [command for command in commands if command[0] == "adb"]
    assert adb_commands == []  # No lease, so no transport to disconnect.
