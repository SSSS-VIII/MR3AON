"""Persistent names, isolated writable state and an instance-bound device handle.

Consumers select a name. Waydroid slots, DHCP addresses and ADB servers remain
implementation details here; the same registry is used by launch and recovery.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unicodedata
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False, indent=4) + "\n"
    if path.is_file() and path.read_text() == encoded:
        path.chmod(0o600)
        return
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".instance-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@dataclass(frozen=True)
class InstanceSpec:
    name: str
    slot: int
    project_root: Path
    work_root: Path

    @property
    def adb_port(self) -> int:
        return 5037 + self.slot

    @property
    def config_path(self) -> Path:
        return self.work_root / "config/maa_pi_config.json"

    def environment(self, serial: str | None = None) -> dict[str, str]:
        env = os.environ.copy()
        env.pop("MR3A_TEST_WORK", None)
        env.pop("MR3A_PICLI_PID", None)
        env.pop("MR3A_ADB_SERIAL", None)
        env.pop("ANDROID_SERIAL", None)
        env.pop("ANDROID_ADB_SERVER_PORT", None)
        env.pop("ADB_SERVER_PORT", None)
        env.update(
            MR3A_INSTANCE_NAME=self.name,
            MR3A_WORK_ROOT=str(self.work_root),
            MR3A_WAYDROID_SLOT=str(self.slot),
            ADB_SERVER_SOCKET=f"tcp:{self.adb_port}",
        )
        if serial:
            env.update(MR3A_ADB_SERIAL=serial, ANDROID_SERIAL=serial)
        return env


class InstanceRegistry:
    def __init__(self, project_root: Path = PROJECT_ROOT):
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / ".mr3a-instances"

    def get(self, name: str = "main") -> InstanceSpec:
        name = unicodedata.normalize("NFC", name)
        if not name or len(name) > 48 or not all(c.isalnum() or c in "_-" for c in name):
            raise ValueError("实例名须为 1–48 个字母、数字、中文、下划线或短横线")
        if name == "main":
            return InstanceSpec(name, 0, self.project_root, self.project_root / "deps/bin")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.root / "registry.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.root / "registry.json"
            entries = json.loads(path.read_text()) if path.exists() else {}
            if not isinstance(entries, dict) or any(type(slot) is not int or not 1 <= slot <= 14 for slot in entries.values()) or len(set(entries.values())) != len(entries):
                raise RuntimeError("实例注册表存在非法或重复编号，拒绝连接其它环境")
            if name not in entries:
                available = set(range(1, 15)) - set(entries.values())
                if not available:
                    raise RuntimeError("实例名额已用完（最多 14 个附加 Android）")
                entries[name] = min(available)
                write_json(path, entries)
            slot = entries[name]
            if type(slot) is not int or not 1 <= slot <= 14 or list(entries.values()).count(slot) != 1:
                raise RuntimeError("实例注册表存在非法或重复编号，拒绝连接其它环境")
            work = self.root / name
            identity = work / "instance.json"
            if identity.exists() and json.loads(identity.read_text()) != {"name": name, "slot": slot}:
                raise RuntimeError("实例注册表与已有环境身份不一致，拒绝切换账号")
            return InstanceSpec(name, slot, self.project_root, work)

    def prepare(self, spec: InstanceSpec, *, migrate_legacy: bool = False) -> None:
        root = spec.work_root
        root.mkdir(parents=True, exist_ok=True)
        identity = root / "instance.json"
        expected_identity = {"name": spec.name, "slot": spec.slot}
        if identity.exists() and json.loads(identity.read_text()) != expected_identity:
            raise RuntimeError("实例环境身份不一致，拒绝覆盖配置")
        write_json(identity, expected_identity)
        for name in ("config", "data", "debug"):
            (root / name).mkdir(mode=0o700, exist_ok=True)
            (root / name).chmod(0o700)
        # Configuration starts empty for a new account; never clone the main
        # task options, login inputs or completion ledger into another name.
        if not spec.config_path.exists():
            write_json(spec.config_path, {
                "controller": {"name": "模拟器"}, "resource": "通用",
                "adb": {"adb_path": shutil.which("adb") or "/usr/bin/adb", "address": "", "name": ""},
                "task": [],
            })
        spec.config_path.chmod(0o600)
        options = root / "config/maa_option.json"
        if not options.exists():
            defaults = spec.project_root / "tools/ci/defaults/maa_option.json"
            write_json(options, json.loads(defaults.read_text()))
        pip = root / "config/pip_config.json"
        if not pip.exists():
            previous = spec.project_root / "config/pip_config.json"
            settings = json.loads(previous.read_text()) if not spec.slot and previous.exists() else {"enable_pip_install": False}
            write_json(pip, settings)
        # Immutable resources remain shared. Only initial data is seeded once,
        # including any existing main-account learned questions/cache.
        source_data = spec.project_root / "assets/resource/data"
        for source in source_data.glob("*"):
            target = root / "data" / source.name
            if source.is_file() and not target.exists():
                shutil.copyfile(source, target)
                target.chmod(0o600)
        interface = json.loads((spec.project_root / "assets/interface.json").read_text())
        assets = spec.project_root / "assets"
        interface["import"] = [str(assets / p) for p in interface.get("import", [])]
        for resource in interface.get("resource", []):
            resource["path"] = [str((assets / p).resolve()) for p in resource["path"]]
        interface["agent"] = {
            "child_exec": str(spec.project_root / ".venv/bin/python"),
            "child_args": ["-u", str(spec.project_root / "agent/main.py")],
        }
        write_json(root / "interface.json", interface)
        if not spec.slot and migrate_legacy:
            self._merge_legacy_rewards(spec)

    def _merge_legacy_rewards(self, spec: InstanceSpec) -> None:
        source = spec.project_root / "assets/debug/reward_shots"
        target = spec.work_root / "debug/reward_shots"
        if not source.exists():
            return
        registry_path = target / "registry.json"
        registry = json.loads(registry_path.read_text()) if registry_path.exists() else {"version": 1, "dirs": []}
        names = set(registry.get("dirs", []))
        for image in source.glob("*/*.png"):
            category = image.parent.name
            destination = target / category / image.name
            names.add(category)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                incoming = hashlib.sha256(image.read_bytes()).hexdigest()
                existing = hashlib.sha256(destination.read_bytes()).hexdigest()
                if incoming == existing:
                    continue
                old = destination if image.stat().st_mtime > destination.stat().st_mtime else image
                history = "历史_" + category
                archive = target / history / (old.stem + "-" + hashlib.sha256(old.read_bytes()).hexdigest()[:12] + ".png")
                archive.parent.mkdir(parents=True, exist_ok=True)
                if not archive.exists():
                    shutil.copy2(old, archive)
                names.add(history)
                if old == image:
                    continue
            shutil.copy2(image, destination)
        registry["dirs"] = sorted(names)
        write_json(registry_path, registry)


class InstanceSession:
    """Name-bound lifecycle and transport; no caller-managed ports or serials.

    Input controllers hold control() for their lifetime. Read-only screenshots
    can be taken without acquiring that exclusive control lease.
    """

    def __init__(self, name: str = "main", *, registry: InstanceRegistry | None = None):
        self.registry = registry or InstanceRegistry()
        self.spec = self.registry.get(name)
        self._serial: str | None = None
        self._owns_control = False

    def _backend(self, *args: str, timeout: float = 200, root: bool = False):
        command = [str(self.spec.project_root / "tools/waydroid-instance"), "--slot", str(self.spec.slot), *args]
        if root:
            command[0:0] = ["sudo", "-n"]
        result = subprocess.run(command, capture_output=True, timeout=timeout, env=self.spec.environment())
        if result.returncode:
            raise RuntimeError(f"实例 {self.spec.name} 的 Waydroid 操作失败：{result.stderr.decode(errors='replace').strip()}")
        return result.stdout.decode(errors="replace")

    def status(self) -> dict[str, str]:
        text = self._backend("status", timeout=20)
        return {k.strip().lower(): v.strip() for line in text.splitlines() if ":" in line for k, v in [line.split(":", 1)]}

    def _address(self) -> str:
        status = self.status()
        address = status.get("ip address", "UNKNOWN")
        if status.get("session") != "RUNNING" or address == "UNKNOWN":
            raise RuntimeError(f"实例 {self.spec.name} 的 Android 尚未运行或没有地址")
        import ipaddress
        target = ipaddress.ip_address(address)
        expected = ipaddress.ip_network(f"192.168.{240 + self.spec.slot}.0/24")
        if target not in expected:
            raise RuntimeError(f"实例 {self.spec.name} 返回了其它环境的地址，拒绝连接")
        return address + ":5555"

    def _adb_result(self, *args: str, timeout: float = 20, target: bool = True, input_data: bytes | None = None):
        command = [shutil.which("adb") or "/usr/bin/adb", "-P", str(self.spec.adb_port)]
        if target:
            if not self._serial:
                self._serial = self._address()
            command.extend(["-s", self._serial])
        command.extend(args)
        return subprocess.run(command, input=input_data, capture_output=True, timeout=timeout, env=self.spec.environment(self._serial))

    def _adb(self, *args: str, timeout: float = 20, target: bool = True):
        result = self._adb_result(*args, timeout=timeout, target=target)
        if result.returncode:
            raise RuntimeError(f"实例 {self.spec.name} 设备操作失败：{result.stderr.decode(errors='replace').strip()}")
        return result.stdout

    def adb(self, *args: str, timeout: float = 20, input_data: bytes | None = None) -> subprocess.CompletedProcess:
        """在持有控制权时执行设备命令，保留二进制输出、stderr 和退出码。

        只开放本实例的设备传输；服务器、连接和目标选择仍由设备层管理。
        宿主文件传输的路径权限由上层控制器按自己的工作目录校验。
        """
        if not self._owns_control:
            raise RuntimeError("ADB 操作须先通过 control() 取得实例控制权")
        host_commands = {
            "devices", "connect", "disconnect", "pair", "start-server", "kill-server",
            "server", "nodaemon", "attach", "detach", "reconnect", "mdns",
            "track-devices", "host-features", "forward", "reverse", "tcpip", "usb",
        }
        if not args or any(not isinstance(arg, str) or "\0" in arg for arg in args):
            raise ValueError("ADB 参数须为不含空字节的字符串")
        if args[0].startswith("-") or args[0] in host_commands:
            raise ValueError("设备目标、ADB 服务器和端口由实例层管理，不能从设备命令切换")
        if not 0 < timeout <= 300:
            raise ValueError("ADB 超时须在 0–300 秒内")
        if input_data is not None and not isinstance(input_data, bytes):
            raise ValueError("ADB 标准输入须为 bytes")
        return self._adb_result(*args, timeout=timeout, input_data=input_data)

    def ensure_ready(self, timeout: float = 180) -> str:
        self._backend("start", timeout=timeout)
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._serial = self._address()
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        self._adb("connect", self._serial, target=False)
        devices = self._adb("devices", target=False).decode()
        if f"{self._serial}\tunauthorized" in devices:
            self._backend("authorize-adb", root=True, timeout=30)
        while time.monotonic() < deadline:
            self._adb("connect", self._serial, target=False)
            devices = self._adb("devices", target=False).decode()
            if f"{self._serial}\tdevice" in devices:
                if self._shell("getprop", "sys.boot_completed").strip() == "1":
                    self._shell("wm", "size", "1280x720")
                    return self._serial
            time.sleep(1)
        raise RuntimeError(f"等待实例 {self.spec.name} 就绪超时")

    def stop(self) -> None:
        try:
            address = self._address()
        except RuntimeError:
            address = None
        # Keep the instance's root manager alive. Normal script recovery then
        # uses its D-Bus service without repeatedly requesting host privileges.
        self._backend("session", "stop")
        subprocess.run([
            "systemctl", "--user", "stop", f"mr3a-waydroid-session-{self.spec.slot}",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if address:
            self._adb("disconnect", address, target=False)
        self._serial = None

    def restart(self) -> str:
        self.stop()
        return self.ensure_ready()

    def shutdown(self) -> None:
        """Explicit full shutdown; recovery's stop() deliberately keeps its manager."""
        with self.control():
            self._backend("stop")
            self._serial = None

    def _shell(self, *args: str) -> str:
        return self._adb("shell", *args).decode(errors="replace")

    def screenshot(self) -> bytes:
        temporary = f"/data/local/tmp/mr3a-shot-{uuid.uuid4().hex}.png"
        try:
            # Write on the device first so graphics-driver stderr cannot corrupt
            # the PNG stream (the existing Waydroid amdgpu.ids issue).
            self._shell("screencap", "-p", temporary)
            image = self._adb("exec-out", "cat", temporary)
            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError(f"实例 {self.spec.name} 返回了无效截图")
            return image
        finally:
            try:
                self._shell("rm", "-f", temporary)
            except (RuntimeError, subprocess.SubprocessError):
                pass

    def tap(self, x: int, y: int) -> None:
        if not self._owns_control:
            raise RuntimeError("输入操作须先通过 control() 取得实例控制权")
        self._shell("input", "tap", str(int(x)), str(int(y)))

    def press_key(self, key: int) -> None:
        if not self._owns_control:
            raise RuntimeError("输入操作须先通过 control() 取得实例控制权")
        self._shell("input", "keyevent", str(int(key)))

    def environment(self) -> dict[str, str]:
        if not self._serial:
            raise RuntimeError("先调用 ensure_ready()，再取得运行环境")
        return self.spec.environment(self._serial)

    def bind_config(self) -> None:
        config = json.loads(self.spec.config_path.read_text())
        serial = self._serial or self._address()
        config["adb"] = {
            "adb_path": shutil.which("adb") or "/usr/bin/adb", "address": serial,
            "name": serial + "-" + (shutil.which("adb") or "/usr/bin/adb"),
        }
        write_json(self.spec.config_path, config)

    @contextmanager
    def control(self):
        self.spec.work_root.mkdir(parents=True, exist_ok=True)
        with (self.spec.work_root / "control.lock").open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError(f"实例 {self.spec.name} 已有控制者；请用其它名字并行运行") from None
            # Adoption must also respect a main runner started by the old run.
            if not self.spec.slot:
                for process in Path("/proc").iterdir():
                    if not process.name.isdigit():
                        continue
                    try:
                        executable = Path(os.readlink(process / "exe")).name.removesuffix(" (deleted)")
                        if executable == "MaaPiCli" and (process / "cwd").resolve() == self.spec.work_root.resolve():
                            raise RuntimeError("main 已有旧入口启动的脚本；请先退出它，或用其它名字")
                    except (OSError, PermissionError):
                        continue
            os.set_inheritable(lock.fileno(), True)
            self._owns_control = True
            try:
                yield lock.fileno()
            finally:
                self._owns_control = False
