#!/usr/bin/python3
"""Named Waydroid instances using the installed 1.6.3 Python implementation.

No RPM-owned file is changed. Adaptations apply only inside this process;
Android images are shared read-only, while mounts, Binder and userdata are not.
"""

from __future__ import annotations

import argparse
import configparser
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import time

PACKAGE = Path("/usr/lib/waydroid")
SUPPORTED_VERSION = "1.6.3"


class Instance:
    def __init__(self, slot: int):
        if not 0 <= slot <= 14:
            raise ValueError("实例编号须为 0–14；0 接管现有默认环境")
        self.slot = slot
        self.name = f"mr3a{slot}"
        self.work = Path(f"/var/lib/waydroid-{self.name}")
        self.bridge = f"wd{self.name}"
        self.subnet = f"192.168.{240 + slot}"
        self.binderfs = f"/dev/binderfs-{self.name}"
        self.container_bus = f"id.waydro.Container.{self.name}"
        self.session_bus = f"id.waydro.Session.{self.name}"
        self.adb_port = 5037 + slot
        if slot == 0:
            self.name = "main"
            self.work = Path("/var/lib/waydroid")
            self.bridge = "waydroid0"
            self.binderfs = "/dev/binderfs"
            self.container_bus = "id.waydro.Container"
            self.session_bus = "id.waydro.Session"

    def adapt_source(self, source: str) -> str:
        if self.slot == 0:
            return source
        source = source.replace("/var/lib/waydroid", str(self.work))
        source = source.replace("/dev/binderfs", self.binderfs)
        source = source.replace("waydroid0", self.bridge)
        for old, new in (
            ("id.waydro.Container", self.container_bus),
            ("id.waydro.Session", self.session_bus),
        ):
            # Keep the D-Bus interface names (ContainerManager etc.) unchanged.
            for quote in ('"', "'"):
                source = source.replace(quote + old + quote, quote + new + quote)
        source = source.replace('"/tmp/tools.log"', f'"/tmp/waydroid-{self.name}-{os.getuid()}.log"')
        return source

    def network_script(self, source: str) -> str:
        if self.slot == 0:
            return source
        source = self.adapt_source(source)
        source = source.replace("/run/waydroid-lxc", f"/run/waydroid-{self.name}-lxc")
        source = source.replace("192.168.240.", self.subnet + ".")
        # Both start and stop must address only this instance's nftables tables.
        source = re.sub(r"\blxc\b(?=[ ;])", "wd_" + self.name, source)
        return source


class InstalledSourceLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, name, path, instance):
        super().__init__(name, path)
        self.instance = instance

    def get_code(self, fullname):
        source = self.get_data(self.path).decode("utf-8")
        return self.source_to_code(self.instance.adapt_source(source), self.path)


class InstalledSourceFinder(importlib.abc.MetaPathFinder):
    def __init__(self, instance):
        self.instance = instance

    def find_spec(self, fullname, path, target=None):
        if fullname != "tools" and not fullname.startswith("tools."):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.origin and Path(spec.origin).is_relative_to(PACKAGE):
            spec.loader = InstalledSourceLoader(fullname, spec.origin, self.instance)
        return spec


def load_installed(instance):
    version_text = (PACKAGE / "tools/config/__init__.py").read_text()
    if not re.search(rf'^version = "{re.escape(SUPPORTED_VERSION)}"$', version_text, re.M):
        raise RuntimeError("Waydroid 包版本已变化；请重新核对实例适配，不能自动套用")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(PACKAGE))
    sys.meta_path.insert(0, InstalledSourceFinder(instance))
    import tools
    if instance.slot == 0:
        return tools

    # Imports still resolve to the RPM tree; never copy or modify its modules.
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    data_home = data_home / f"waydroid-{instance.name}"
    tools.config.session_defaults.update(
        xdg_data_home=str(data_home),
        waydroid_user_state=str(data_home / "waydroid"),
        waydroid_data=str(data_home / "android-data"),
    )
    if os.geteuid() != 0:
        (data_home / "waydroid").mkdir(parents=True, exist_ok=True)
    for key in ("BINDER_DRIVERS", "VNDBINDER_DRIVERS", "HWBINDER_DRIVERS"):
        original = getattr(tools.helpers.drivers, key)
        setattr(tools.helpers.drivers, key, [name + "-" + instance.name for name in original])

    original_run = tools.helpers.run.user

    def run(args, command, *positional, **kwargs):
        if command and command[0] == str(PACKAGE / "data/scripts/waydroid-net.sh"):
            command = [str(instance.work / "waydroid-net.sh"), *command[1:]]
        if command[:2] == ["ln", "-s"] and command[-1] == "/dev/":
            # binderfs also exposes generic binder/control/features entries;
            # only publish this instance's explicitly suffixed device names.
            command = ["ln", "-s", *[
                value for value in command[2:-1]
                if Path(value).name.endswith("-" + instance.name)
            ], "/dev/"]
        return original_run(args, command, *positional, **kwargs)

    tools.helpers.run.user = run
    original_lxc_config = tools.helpers.lxc.set_lxc_config

    def set_lxc_config(args):
        original_lxc_config(args)
        path = instance.work / "lxc/waydroid/config"
        path.write_text(instance.adapt_source(path.read_text()))

    tools.helpers.lxc.set_lxc_config = set_lxc_config
    original_prepare = tools.actions.container_manager.prepare_drivers_once

    def prepare_drivers(args):
        original_prepare(args)
        args.vendor_type = tools.config.load(args)["waydroid"]["vendor_type"]
        # Device major/minor numbers may change after the host reboots. Rebuild
        # the generated allow-list before binding a new Android session.
        set_lxc_config(args)

    tools.actions.container_manager.prepare_drivers_once = prepare_drivers

    # Upstream stops every sensord by process name; disable that singleton and
    # host NFC manipulation for a secondary Android instead of touching main.
    original_which = tools.actions.container_manager.which
    tools.actions.container_manager.which = lambda name: (
        None if name in {"waydroid-sensord", "systemctl", "start", "stop"} else original_which(name)
    )
    # Secondary Android must not interact with the host's shared clipboard or
    # notification state. UserMonitor remains active to signal Android readiness.
    for service in (tools.services.clipboard_manager, tools.services.notification_manager):
        service.start = lambda *args, **kwargs: None
        service.stop = lambda *args, **kwargs: None

    def disallow_image_update(*args, **kwargs):
        raise RuntimeError("次实例共用只读系统镜像，不允许从次实例更新镜像")

    tools.helpers.images.replace = disallow_image_update
    tools.helpers.images.get = disallow_image_update
    return tools


def create(instance, tools):
    if instance.slot == 0:
        raise RuntimeError("默认实例直接复用已有环境，不允许重新创建")
    if os.geteuid() != 0:
        raise RuntimeError("创建实例需 sudo；会话和窗口须用普通用户运行")
    if instance.work.exists():
        raise RuntimeError(f"实例目录已存在，拒绝覆盖：{instance.work}")
    cfg = configparser.ConfigParser()
    cfg.read("/var/lib/waydroid/waydroid.cfg")
    if cfg.get("waydroid", "vendor_type") != "MAINLINE":
        raise RuntimeError("当前适配仅支持 MAINLINE 镜像")
    images = Path(cfg.get("waydroid", "images_path"))
    for image in ("system.img", "vendor.img"):
        if not (images / image).is_file():
            raise RuntimeError(f"缺少主环境系统镜像：{images / image}")
    routes = subprocess.check_output(["ip", "-j", "route"], text=True)
    import ipaddress

    network = ipaddress.ip_network(instance.subnet + ".0/24")
    for route in json.loads(routes):
        destination = route.get("dst", "default")
        if destination != "default" and network.overlaps(ipaddress.ip_network(destination, strict=False)):
            raise RuntimeError(f"实例子网与已有路由冲突：{destination}")
    instance.work.mkdir(mode=0o755)
    for directory in ("rootfs", "overlay_rw/system", "overlay_rw/vendor", "overlay_work"):
        (instance.work / directory).mkdir(parents=True, exist_ok=True)
    # Snapshot local ARM translation modifications without copying Android data.
    subprocess.run(
        ["cp", "-a", "--reflink=auto", "/var/lib/waydroid/overlay", str(instance.work / "overlay")],
        check=True,
    )
    cfg["waydroid"]["auto_adb"] = "True"
    for key, group in (("binder", "BINDER_DRIVERS"), ("vndbinder", "VNDBINDER_DRIVERS"), ("hwbinder", "HWBINDER_DRIVERS")):
        cfg["waydroid"][key] = getattr(tools.helpers.drivers, group)[0]
    with (instance.work / "waydroid.cfg").open("w") as stream:
        cfg.write(stream)
    tools.config.defaults["preinstalled_images_paths"].append(str(images))
    net = instance.work / "waydroid-net.sh"
    net.write_text(instance.network_script((PACKAGE / "data/scripts/waydroid-net.sh").read_text()))
    net.chmod(0o755)
    args = argparse.Namespace(
        vendor_type="MAINLINE", images_path=str(images),
        system_ota=cfg["waydroid"]["system_ota"], vendor_ota=cfg["waydroid"]["vendor_ota"],
        action="create", verbose=False, quiet=False, details_to_stdout=True,
    )
    tools.prep_args(args)
    tools.helpers.logging.init(args)
    tools.helpers.drivers.setupBinderNodes(args)
    tools.helpers.lxc.setup_host_perms(args)
    tools.helpers.lxc.set_lxc_config(args)
    tools.helpers.lxc.make_base_props(args)
    policy = Path(f"/etc/dbus-1/system.d/{instance.container_bus}.conf")
    policy.write_text(
        Path("/usr/share/dbus-1/system.d/id.waydro.Container.conf").read_text().replace(
            "id.waydro.Container", instance.container_bus
        )
    )
    (instance.work / "instance.json").write_text(json.dumps({
        "slot": instance.slot, "package_version": SUPPORTED_VERSION,
        "shared_images": str(images), "bridge": instance.bridge,
    }, indent=2) + "\n")
    print(f"已创建 {instance.name}：{instance.work}，子网 {network}")


def authorize_adb(instance):
    """Authorize only the invoking user's public host key in this Android."""
    if os.geteuid() != 0 or not os.environ.get("SUDO_UID"):
        raise RuntimeError("请由普通用户通过 sudo 执行 authorize-adb")
    account = pwd.getpwuid(int(os.environ["SUDO_UID"]))
    key = (Path(account.pw_dir) / ".android/adbkey.pub").read_bytes().strip()
    if not key or b"\n" in key:
        raise RuntimeError("ADB 公钥格式不正确，请先 adb start-server")
    subprocess.run([
        "lxc-attach", "-P", str(instance.work / "lxc"), "-n", "waydroid", "--",
        "/system/bin/sh", "-c",
        "set -e; umask 027; mkdir -p /data/misc/adb; key=$(cat); "
        'grep -qxF "$key" /data/misc/adb/adb_keys 2>/dev/null || '
        'printf \'%s\\n\' "$key" >> /data/misc/adb/adb_keys; '
        "chown system:shell /data/misc/adb/adb_keys; "
        "chmod 640 /data/misc/adb/adb_keys; "
        "restorecon /data/misc/adb/adb_keys; setprop ctl.restart adbd",
    ], input=key + b"\n", check=True)
    print(f"已为次实例 {instance.name} 授权当前用户的 ADB 公钥")


def manage(instance, action, *, show_window=True):
    if os.geteuid() == 0:
        raise RuntimeError("start/stop 必须在桌面普通用户下运行；工具自行提权启动容器")
    command = ["/usr/bin/python3", str(Path(__file__).resolve()), "--slot", str(instance.slot)]
    system_unit = f"mr3a-waydroid-{instance.slot}" if instance.slot else "waydroid-container"
    user_unit = f"mr3a-waydroid-session-{instance.slot}"
    if action == "stop":
        address = None
        lease = Path(f"/var/lib/misc/dnsmasq.{instance.bridge}.leases")
        if lease.exists():
            rows = [line.split() for line in lease.read_text().splitlines()]
            if rows and len(rows[0]) >= 3:
                import ipaddress
                address = str(ipaddress.IPv4Address(rows[0][2])) + ":5555"
        # Slot zero owns the packaged daemon; other slots own dedicated units.
        # Never kill by process name or flush another instance's network state.
        subprocess.run([
            "busctl", "--user", "call", instance.session_bus,
            "/SessionManager", "id.waydro.SessionManager", "Stop",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for prefix, unit in ((["systemctl", "--user"], user_unit), (["sudo", "-n", "systemctl"], system_unit)):
            loaded = subprocess.check_output([*prefix, "show", "--property=LoadState", "--value", unit], text=True).strip()
            if loaded != "not-found":
                subprocess.run([*prefix, "stop", unit], check=True)
        if address:
            # ADB is host transport infrastructure, not an Android container.
            # A stale server must not block an already completed shutdown.
            try:
                subprocess.run(["adb", "-P", str(instance.adb_port), "disconnect", address], check=True, timeout=5)
            except (subprocess.SubprocessError, OSError) as exc:
                print(f"Waydroid 已关闭；清理 ADB 连接失败：{exc}", file=sys.stderr)
        return
    if instance.slot and not (instance.work / "instance.json").is_file():
        subprocess.run(["sudo", "-n", *command, "create"], check=True)
    active = subprocess.run(["systemctl", "is-active", "--quiet", system_unit])
    if active.returncode:
        if instance.slot:
            subprocess.run([
                "sudo", "-n", "systemd-run", "--unit=" + system_unit, "--collect",
                *command, "container", "start",
            ], check=True)
        else:
            subprocess.run(["sudo", "-n", "systemctl", "start", system_unit], check=True)
    # Wait for the dedicated bus name rather than assuming systemd's exec means
    # the container daemon is ready to receive session requests.
    for _ in range(50):
        result = subprocess.run([
            "busctl", "--system", "call", instance.container_bus,
            "/ContainerManager", "id.waydro.ContainerManager", "GetSession",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("等待次实例 D-Bus 容器服务超时；请查看对应 systemd 日志")
    active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", user_unit])
    def session_ready():
        return subprocess.run([
            "busctl", "--user", "call", instance.session_bus,
            "/SessionManager", "org.freedesktop.DBus.Peer", "Ping",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0

    if active.returncode and not session_ready():
        subprocess.run([
            "systemd-run", "--user", "--unit=" + user_unit, "--collect",
            "--setenv=WAYLAND_DISPLAY", "--setenv=XDG_RUNTIME_DIR",
            *command, "session", "start",
        ], check=True)
    # show-full-ui starts a session itself when its D-Bus object is not ready.
    # Waiting here prevents it racing the managed session during cold boot.
    for _ in range(120):
        if session_ready():
            break
        time.sleep(1)
    else:
        raise RuntimeError("等待次实例 Android 会话超时；请查看对应用户服务日志")
    if show_window:
        subprocess.run([*command, "show-full-ui"], check=True, timeout=30)
    subprocess.run([*command, "status"], check=True)
    print(f"ADB server: localhost:{instance.adb_port}")


def main():
    os.umask(0o022)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", type=int, required=True, help="1–14，固定映射独立网络与服务")
    parser.add_argument("--no-window", action="store_true", help="start 只准备后台 Android 会话，不打开桌面窗口")
    parser.add_argument("action", choices=("create", "start", "stop", "authorize-adb", "status", "session", "container", "show-full-ui", "adb", "shell", "prop", "app", "log"))
    args, remaining = parser.parse_known_args()
    if args.no_window and args.action != "start":
        parser.error("--no-window 仅用于 start")
    instance = Instance(args.slot)
    # Avoid publishing secondary Android devices into the main script's ADB
    # server. Each slot still shares the installed adb binary and host key.
    os.environ["ADB_SERVER_SOCKET"] = f"tcp:{instance.adb_port}"
    if args.action in {"start", "stop"}:
        if remaining:
            parser.error("start/stop 不接受额外参数")
        manage(instance, args.action, show_window=not args.no_window)
        return 0
    tools = load_installed(instance)
    if args.action == "create":
        if remaining:
            parser.error("create 不接受额外参数")
        create(instance, tools)
        return 0
    if instance.slot and not (instance.work / "instance.json").is_file():
        raise RuntimeError("请先 sudo tools/waydroid-instance --slot N create")
    if args.action == "authorize-adb":
        if remaining:
            parser.error("authorize-adb 不接受额外参数")
        authorize_adb(instance)
        return 0
    sys.argv = ["waydroid", args.action, *remaining]
    return tools.main()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
