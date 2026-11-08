#!/usr/bin/env python3
"""Start the prepared, isolated original-client arena environment."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid

from arena_local import FOLDER, LocalClient, PACKAGE, ROOT
from runtime import InstanceSession

APK_SHA256 = "047097ea15d5db1a9e77131a1e267ee11f19087d5211f6be265278331e1198da"
SERVER = "/data/local/tmp/mr3a-frida16-server"
BUNDLE = "84218715a6c56ab1c410ee5b9b4ec6dd.ab"
JAVA_TRANSPORT = r'''
rpc.exports={
 quietStatistics:function(){return new Promise(function(resolve,reject){Java.perform(function(){
  try {
   var C=Java.use('com.reyun.tracking.sdk.ReYunWorkHandler');
   var main=Java.use('android.os.Looper').getMainLooper();
   var stopped=[];
   if(C.sHandlers.value!==null){
    var it=C.sHandlers.value.values().iterator();
    while(it.hasNext()){
     var instance=Java.cast(it.next(),C);var h=instance.mWorkHandler.value;
     if(h!==null){
      if(h.getLooper().equals(main))throw Error('Refusing to stop the Android main looper');
      instance.clearTasks();h.removeCallbacksAndMessages(null);
      stopped.push(h.getLooper().getThread().getName().toString());h.getLooper().quitSafely();
     }
    }
   }
   resolve(stopped);
  }catch(e){reject(e.toString());}
 });});},
 send:function(code){return new Promise(function(resolve,reject){Java.perform(function(){
  try{Java.use('com.unity3d.player.UnityPlayer').UnitySendMessage('GameManager','DoString',code);resolve(true);}
  catch(e){reject(e.toString());}
 });});}
};
'''


def owned_display_pid(pid):
    try:
        args = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
        allowed = {str(ROOT / 'tools/arena_display.py').encode(), b'tools/arena_display.py',
                   b'debug/arena-client/gameonly/nested_display_child.py'}
        return Path(os.fsdecode(args[0])).name == 'gamescope' and any(arg in allowed for arg in args)
    except (OSError, ValueError):
        return False


def ensure_display(record):
    if record.exists():
        try:
            data = json.loads(record.read_text())
        except (ValueError, OSError):
            data = {}
        socket = Path(data.get('XDG_RUNTIME_DIR', '/run/user/1000')) / data.get('WAYLAND_DISPLAY', '')
        if socket.is_socket() and owned_display_pid(data.get('gamescope_pid', -1)):
            return data, False
        if owned_display_pid(data.get('gamescope_pid', -1)):
            os.kill(data['gamescope_pid'], signal.SIGTERM)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.unlink(missing_ok=True)
    with (record.parent / 'gamescope-arena.log').open('ab') as log:
        process = subprocess.Popen(['gamescope', '-W', '1280', '-H', '720', '-w', '1280', '-h', '720',
                                    '-r', '60', '--expose-wayland', '--backend', 'wayland', '--',
                                    sys.executable, str(ROOT / 'tools/arena_display.py')],
                                   cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('The local arena compositor exited; see gamescope-arena.log')
        if record.exists():
            data = json.loads(record.read_text())
            if data.get('gamescope_pid') == process.pid:
                return data, True
        time.sleep(0.1)
    process.terminate()
    raise TimeoutError('The local arena compositor did not initialize')


def focus_display(data):
    pid = data.get('gamescope_pid', -1)
    if not owned_display_pid(pid):
        return
    try:
        windows = json.loads(subprocess.check_output(['niri', 'msg', '-j', 'windows'], text=True))
        window = next((w for w in windows if w.get('pid') == pid), None)
        if window:
            identity = str(window['id'])
            for args in [('move-window-to-floating', '--id', identity),
                         ('set-window-width', '--id', identity, '1280'),
                         ('set-window-height', '--id', identity, '720'), ('focus-window', '--id', identity)]:
                subprocess.run(['niri', 'msg', 'action', *args], check=True, capture_output=True)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass


def root_shell(session, source):
    return session._backend("shell", "--", "--", "sh", "-c", source, root=True, timeout=30)


def app_uid(session):
    result = session.adb("shell", "cmd", "package", "list", "packages", "-U", PACKAGE)
    result.check_returncode()
    match = re.fullmatch(r"package:" + re.escape(PACKAGE) + r" uid:(\d+)\s*", result.stdout.decode())
    if not match or int(match[1]) < 10000:
        raise RuntimeError("The arena client package or its isolated UID is missing")
    return int(match[1])


def block_network(session, uid):
    for family in ("-4", "-6"):
        rules = session.adb("shell", "ip", family, "rule", "show").stdout.decode()
        expected = f"uidrange {uid}-{uid} prohibit"
        if expected not in rules:
            root_shell(session, f"ip {family} rule add priority 100 uidrange {uid}-{uid} prohibit")
        verified = session.adb("shell", "ip", family, "rule", "show").stdout.decode()
        if expected not in verified:
            raise RuntimeError(f"Could not verify arena {family} network isolation")


def verify_resources(session, report):
    paths = session.adb("shell", "pm", "path", PACKAGE).stdout.decode().splitlines()
    apk = next((line.removeprefix("package:") for line in paths if line.endswith("/base.apk")), None)
    if not apk:
        raise RuntimeError("Arena APK is not installed")
    actual = session.adb("shell", "sha256sum", apk).stdout.decode().split()[0]
    if actual != APK_SHA256:
        raise RuntimeError("This bootstrap requires the recorded original APK build")
    receipt = json.loads(report.read_text())
    path = f"/sdcard/Android/data/{PACKAGE}/files/DynamicContent/AssetBundles/{BUNDLE}"
    actual = session.adb("shell", "sha256sum", path).stdout.decode().split()[0]
    if actual != receipt["patched_sha256"]:
        raise RuntimeError("Installed Lua bridge differs from its local build report")
    source_hash = hashlib.sha256((ROOT / "arena/Local/client_bridge.lua").read_bytes()).hexdigest()
    if source_hash != receipt["bridge_sha256"]:
        raise RuntimeError("Rebuild and install the updated local bridge before starting")


def install_private_key(session, source, uid):
    if len(source.read_bytes()) != 16:
        raise ValueError("Invalid local resource key length")
    temporary = "/data/local/tmp/mr3a-arena-key-" + uuid.uuid4().hex
    session.adb("push", str(source.resolve()), temporary).check_returncode()
    backing = f"/data/media/0/Android/data/{PACKAGE}/files/arena-control"
    root_shell(session, f"mkdir -p {backing} && chown {uid}:1078 {backing} && chmod 2770 {backing} && "
               f"cp {temporary} {backing}/resource-key && chown {uid}:1078 {backing}/resource-key && "
               f"chmod 600 {backing}/resource-key && rm {temporary}")
    session.adb("shell", "touch", f"{FOLDER}/offline.json").check_returncode()


def start_server(session, binary):
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    remote = root_shell(session, f"sha256sum {SERVER} 2>/dev/null").split()
    if not remote or remote[0] != digest:
        temporary = "/data/local/tmp/mr3a-server-" + uuid.uuid4().hex
        session.adb("push", str(binary.resolve()), temporary).check_returncode()
        root_shell(session, f"cp {temporary} {SERVER} && chmod 700 {SERVER} && chown 0:0 {SERVER} && rm {temporary}")
    output = root_shell(session, f"{SERVER} -l 0.0.0.0:27042 >/data/local/tmp/mr3a-frida16-server.log 2>&1 & echo $!")
    if not output.strip().isdigit():
        raise RuntimeError("Could not start the isolated temporary Java transport")
    return int(output.strip())


def stop_server(session, pid):
    path = session._backend("shell", "--", "--", "readlink", f"/proc/{pid}/exe", root=True, timeout=15).strip()
    if path == SERVER:
        session._backend("shell", "--", "--", "kill", str(pid), root=True, timeout=15)


def early_boot(session, server_binary):
    import frida
    if frida.__version__ != "16.7.19":
        raise RuntimeError("The verified native Java bootstrap uses Frida 16.7.19")
    remote = f"{FOLDER}/bootstrap-{uuid.uuid4().hex}.lua"
    ack = f"{FOLDER}/boot-launch.txt"
    session.adb("push", str(ROOT / "arena/Local/bootstrap.lua"), remote).check_returncode()
    server_pid = start_server(session, server_binary)
    attachment = None
    try:
        android_pid = int(session.adb("shell", "pidof", PACKAGE).stdout.decode().strip())
        address = session._address().split(":")[0] + ":27042"
        device = frida.get_device_manager().add_remote_device(address)
        attachment = device.attach(android_pid, realm="native")
        script = attachment.create_script(JAVA_TRANSPORT)
        script.load()
        stopped = script.exports_sync.quiet_statistics()
        print(f"已停止隔离实例的 {len(stopped)} 个统计重试队列", flush=True)
        # The first successful command records its result before the delayed Lua
        # module load; retries never initialize the same process twice.
        code = ("if not MR3A_BOOT_QUEUED and CS.GameManager.Instance and "
                "tostring(CS.GameManager.Instance:GetCurFSMStateID())=='Logo: 2' and "
                "CS.BaseFramework.Resource.ResourceManager.Instance.Manifest then "
                "MR3A_BOOT_QUEUED=true;local ok,r=pcall(function() return assert(load("
                "CS.System.IO.File.ReadAllText(" + json.dumps(remote) + "),'@mr3a-bootstrap'))() end);"
                "CS.System.IO.File.WriteAllText(" + json.dumps(ack) +
                ",ok and tostring(r) or ('ERROR '..tostring(r))) end")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            script.exports_sync.send(code)
            time.sleep(0.2)
            output = session.adb("shell", "cat", ack)
            if output.returncode == 0:
                message = output.stdout.decode()
                if message.startswith("ERROR"):
                    raise RuntimeError(message)
                script.exports_sync.quiet_statistics()
                return
        raise TimeoutError("Original client did not acknowledge local initialization")
    finally:
        if attachment is not None:
            attachment.detach()
        stop_server(session, server_pid)
        session.adb("shell", "rm", "-f", remote)


def wait_job(client, expression, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = client.execute("return " + expression, timeout=3)
        if value and value.get("done"):
            if value.get("error"):
                raise RuntimeError(value["error"])
            return value
        time.sleep(0.1)
    raise TimeoutError("Local arena initialization did not finish")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--chapter", type=int, default=1)
    p.add_argument("--level", type=int, default=1)
    p.add_argument("--restart", action="store_true", help="Restart only the arena application")
    p.add_argument("--cold", action="store_true", help="Restart only the arena Android instance")
    p.add_argument("--paused", action="store_true")
    p.add_argument("--no-focus", action="store_true")
    p.add_argument("--stop", action="store_true", help="Stop arena and its own nested display")
    base = ROOT / "debug/arena-client"
    p.add_argument("--key-file", type=Path, default=base / "raw/bundle-key")
    p.add_argument("--server-binary", type=Path, default=base / "recovery-tools/frida-server-16.7.19-android-x86_64")
    p.add_argument("--bridge-report", type=Path, default=base / "gameonly/lua-resource-bridge/local-bridge-v3.report.json")
    a = p.parse_args()
    if not 0 <= a.seed <= 2147483647 or a.chapter < 1 or a.level < 1:
        p.error("Invalid seed, chapter or level")
    display = base / "gameonly/nested-display.json"
    session = InstanceSession("arena")
    if a.stop:
        with session.control():
            session.shutdown()
        if display.exists():
            data = json.loads(display.read_text())
            pid = data.get('gamescope_pid', -1)
            if owned_display_pid(pid):
                os.kill(pid, signal.SIGTERM)
            display.unlink(missing_ok=True)
        print('已关闭 arena，本地资源和配置保留。')
        return
    display_data, new_display = ensure_display(display)
    for key, value in display_data.items():
        if key in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_RUNTIME_DIR") and value:
            os.environ[key] = value
    client = LocalClient(session)
    reuse = False
    if not a.restart and not a.cold and not new_display:
        try:
            state = client.execute("return MR3A and MR3A.state()", timeout=1)
            reuse = bool(state and state.get("only") and state.get("offline") and state.get("state") == "Game: 8")
        except (RuntimeError, TimeoutError):
            pass
    if not reuse:
        print("启动隔离的本地竞技场……", flush=True)
        with session.control():
            if a.cold or new_display:
                session.shutdown()
            session.ensure_ready()
            last_pid = session.adb("shell", "cat", "/proc/sys/kernel/ns_last_pid").stdout.decode().strip()
            if last_pid.isdigit() and int(last_pid) >= 60000:
                print("重置 arena 的进程命名空间编号……", flush=True)
                session.shutdown()
                session.ensure_ready()
            uid = app_uid(session)
            block_network(session, uid)
            verify_resources(session, a.bridge_report)
            session.adb("shell", "am", "force-stop", PACKAGE).check_returncode()
            install_private_key(session, a.key_file, uid)
            for name in ("command.json", "ready.json", "boot-launch.txt", "boot-loaded.txt"):
                session.adb("shell", "rm", "-f", f"{FOLDER}/{name}").check_returncode()
            activity = session.adb("shell", "cmd", "package", "resolve-activity", "--brief", PACKAGE).stdout.decode().strip().splitlines()[-1]
            if not activity.startswith(PACKAGE + "/"):
                raise RuntimeError("Unexpected client activity")
            session.adb("shell", "am", "start", "-W", "-n", activity, timeout=90).check_returncode()
            # Complete the original Java/SDK initialization before attaching the
            # short-lived native Java transport. Attaching during initialization
            # was observed to make the client exit with status zero.
            print("等待原客户端完成启动初始化……", flush=True)
            time.sleep(10)
            early_boot(session, a.server_binary)
        deadline = time.monotonic() + 60
        while True:
            try:
                client.execute("return CheckLoadLuaComplete()", timeout=2)
                break
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise
        client.execute("CS.Patch.Instance.CurrentState=CS.Patch.State.__CastFrom(100);return true")
        client.load_environment()
        client.execute(f"MR3A.seed={a.seed};return MR3A.prepare({a.chapter},{a.level})")
        client.execute("return MR3A.load_audio()")
        wait_job(client, "MR3A.audio")
        client.execute("return MR3A.enter()")
    else:
        client.load_environment()
        client.execute(f"return MR3A.reset({a.seed},{a.chapter},{a.level})")
    wait_job(client, "MR3A.resetJob")
    state = client.execute("return MR3A.state()")
    if state.get("maxHealth") != 5000:
        raise RuntimeError("Level-one Xiaohei did not initialize with the expected health")
    client.execute("return MR3A.enable_keyboard()")
    if not a.paused:
        client.execute("return MR3A.resume()")
    if not a.no_focus:
        focus_display(display_data)
    print(f"已就绪：疾风／小黑／章节 {a.chapter}／第 {a.level} 段／种子 {a.seed}" + ("（已暂停）" if a.paused else ""), flush=True)
    print("K/空格/W/↑ 跳跃，S/↓ 下翻，P 暂停/继续，R 重开，N 换种子，. 单步", flush=True)


if __name__ == "__main__":
    main()
