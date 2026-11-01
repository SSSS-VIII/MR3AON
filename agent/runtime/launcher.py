"""The single run entry; all environment selection is by persistent name."""

import argparse
import json
import os
import subprocess
import sys

from runtime.instances import InstanceRegistry, InstanceSession


def main():
    parser = argparse.ArgumentParser(description="按名字启动 MR3A；省略名字使用现有 main 环境")
    parser.add_argument("name", nargs="?", default="main")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--configure", action="store_true", help="配置当前名字的任务和账号选项")
    parser.add_argument("--task", action="append", default=[], help="仅本次运行指定任务，不改保存的任务计划")
    mode.add_argument("--prepare", action="store_true", help="初始化运行文件，不启动 Android 或游戏")
    mode.add_argument("--check", action="store_true", help="准备并检查 Android 连接，不运行游戏任务")
    mode.add_argument("--stop", action="store_true", help="关闭该实例窗口及 Waydroid 后台，保留配置和账号数据；请先退出同名脚本")
    args = parser.parse_args()
    if args.configure and args.task:
        parser.error("--task 仅用于本次执行，不能与 --configure 同时使用")
    if args.stop and args.task:
        parser.error("--stop 不能与 --task 同时使用")
    registry = InstanceRegistry()
    session = InstanceSession(args.name, registry=registry)
    if args.stop:
        session.shutdown()
        print(f"实例 {session.spec.name} 已关闭，配置和账号数据保留")
        return 0
    if args.prepare:
        registry.prepare(session.spec)
        print(f"实例 {session.spec.name}：{session.spec.work_root}")
        return 0
    if args.check:
        registry.prepare(session.spec)
        session.ensure_ready()
        print(f"实例 {session.spec.name} 已就绪：{session.spec.work_root}")
        return 0
    with session.control():
        registry.prepare(session.spec, migrate_legacy=True)
        session.ensure_ready()
        session.bind_config()
        binary = session.spec.project_root / "deps/bin/MaaPiCli"
        support = subprocess.run([str(binary), "--help"], cwd=session.spec.work_root, capture_output=True, text=True, check=True)
        if "--user-dir" not in support.stdout:
            raise RuntimeError("共享 MaaPiCli 尚未支持实例目录，请先重编本地定制版本")
        command = [str(binary), "--user-dir", str(session.spec.work_root), "--resource-dir", str(session.spec.work_root)]
        config = json.loads(session.spec.config_path.read_text())
        if not args.configure and (config.get("task") or args.task):
            command.append("-d")
        elif not sys.stdin.isatty():
            raise RuntimeError(f"实例 {session.spec.name} 尚无任务，请在终端执行 ./run {session.spec.name} --configure")
        for task in args.task:
            command.extend(["--task", task])
        env = session.environment()
        env["MR3A_PICLI_PID"] = str(os.getpid())
        os.chdir(session.spec.work_root)
        print(f"运行实例 {session.spec.name}：{session.spec.work_root}", flush=True)
        os.execve(binary, command, env)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
