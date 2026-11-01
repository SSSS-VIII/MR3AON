"""Name-based screenshot helper for local diagnostics, not an agent service."""

import argparse
from datetime import datetime
from pathlib import Path

from runtime import InstanceSession


def main():
    parser = argparse.ArgumentParser(description="截图保存到所选实例的 debug/adb-shots")
    parser.add_argument("name", nargs="?", default="main")
    parser.add_argument("label", nargs="?")
    args = parser.parse_args()
    session = InstanceSession(args.name)
    session.registry.prepare(session.spec)
    session.ensure_ready()
    label = Path(args.label).stem if args.label else datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if not label or label in {".", ".."}:
        parser.error("截图文件名不能为空")
    target = session.spec.work_root / "debug/adb-shots" / (label + ".png")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(session.screenshot())
    print(target)


if __name__ == "__main__":
    main()
