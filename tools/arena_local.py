#!/usr/bin/env python3
"""Operate the isolated arena client's local Lua bridge through InstanceSession."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid
from contextlib import nullcontext

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
PACKAGE = "com.pandadastudio.ninjamustdie3"
FOLDER = f"/sdcard/Android/data/{PACKAGE}/files/arena-control"


class LocalClient:
    def __init__(self, session):
        if session.spec.name != "arena":
            raise ValueError("Local client controls are restricted to the isolated arena instance")
        self.session = session

    def execute(self, code, timeout=20, *, lease_held=False):
        if not isinstance(code, str) or len(code.encode("utf8")) >= 1048576:
            raise ValueError("Local command must be a string smaller than 1 MiB")
        identity = uuid.uuid4().hex
        remote = f"{FOLDER}/command-{identity}.tmp"
        request = {"id": identity, "code": code}
        with (nullcontext() if lease_held else self.session.control()), tempfile.TemporaryDirectory(prefix="mr3a-arena-") as folder:
            path = Path(folder) / "request.json"
            path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf8")
            result = self.session.adb("push", str(path), remote)
            result.check_returncode()
            self.session.adb("shell", "mv", remote, f"{FOLDER}/command.json").check_returncode()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                output = self.session.adb("shell", "cat", f"{FOLDER}/result.json")
                try:
                    response = json.loads(output.stdout) if output.returncode == 0 else {}
                except (ValueError, UnicodeError):
                    response = {}
                if response.get("id") == identity:
                    # The original bridge reads/parses command.json every render
                    # frame, even after acknowledging its ID. Do not leave a large
                    # environment/annotation script in that hot path. The same
                    # InstanceSession control lease still owns this request slot.
                    self.session.adb("shell", "rm", "-f", f"{FOLDER}/command.json").check_returncode()
                    if not response.get("ok"):
                        raise RuntimeError(response.get("error", "Local command failed"))
                    return response.get("result")
                time.sleep(0.05)
        raise TimeoutError("Arena bridge did not answer; check SDK dialog and bridge readiness")

    def load_environment(self):
        catalog = ROOT / "debug/arena-client/gameonly/gale-catalog-native.json"
        native = ROOT / "arena/Local/native_selection.lua"
        if native.exists():
            if not catalog.exists():
                raise RuntimeError("Build the Gale catalog with tools/arena_gale_catalog.py first")
            with self.session.control():
                self.session.adb("push", str(catalog), f"{FOLDER}/catalog-native.tmp").check_returncode()
                self.session.adb("shell", "mv", f"{FOLDER}/catalog-native.tmp", f"{FOLDER}/catalog-native.json").check_returncode()
        chunks = []
        for name in ("environment", "native_mount", "native_selection", "native_boss", "native_menu"):
            path = ROOT / f"arena/Local/{name}.lua"
            if path.exists():
                chunks.append("assert(load(" + json.dumps(path.read_text(), ensure_ascii=False) + ", '@mr3a-" + name + "'))()")
        return self.execute(";".join(chunks) + ";return MR3A.state()")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("load", "state", "pause", "resume", "enter", "result", "layout", "load_audio", "parameters"):
        sub.add_parser(name)
    advance = sub.add_parser("advance")
    advance.add_argument("ticks", type=int, help="Original 0.02-second physics ticks (1..600)")
    advance.add_argument("--action", choices=("none", "jump", "down"), default="none")
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--chapter", type=int, default=1)
    prepare.add_argument("--level", type=int, default=1)
    reset = sub.add_parser("reset")
    reset.add_argument("--seed", type=int, default=1)
    reset.add_argument("--chapter", type=int, default=1)
    reset.add_argument("--level", type=int, default=1)
    run = sub.add_parser("exec")
    run.add_argument("code")
    runfile = sub.add_parser("exec-file")
    runfile.add_argument("path", type=Path)
    shot = sub.add_parser("screenshot")
    shot.add_argument("path", type=Path)
    a = p.parse_args()
    from runtime import InstanceSession
    client = LocalClient(InstanceSession("arena"))
    if a.command == "screenshot":
        a.path.parent.mkdir(parents=True, exist_ok=True)
        a.path.write_bytes(client.session.screenshot())
        print(a.path)
        return
    if a.command == "load":
        result = client.load_environment()
    elif a.command == "exec":
        result = client.execute(a.code)
    elif a.command == "exec-file":
        result = client.execute(a.path.read_text())
    elif a.command == "prepare":
        if a.chapter < 1 or a.level < 1:
            p.error("chapter and level must be positive")
        result = client.execute(f"return MR3A.prepare({a.chapter},{a.level})")
    elif a.command == "advance":
        result = client.execute(f"return MR3A.advance({a.ticks},{json.dumps(a.action)})")
    elif a.command == "reset":
        result = client.execute(f"return MR3A.reset({a.seed},{a.chapter},{a.level})")
    else:
        result = client.execute(f"return MR3A.{a.command}()")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
