"""The single run entry; all environment selection is by persistent name."""

import argparse
from contextlib import ExitStack
import json
import os
import signal
import subprocess
import sys
import tempfile

from runtime.instances import InstanceRegistry, InstanceSession
from runtime.task_options import build_task_config, load_task_interface, parse_task_options


def main():
    parser = argparse.ArgumentParser(description="按名字启动 MR3A；省略名字使用现有 main 环境")
    parser.add_argument("name", nargs="?", default="main")
    parser.add_argument("--no-window", action="store_true", help="后台启动 Android，不打开桌面窗口；截图和输入照常可用")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--configure", action="store_true", help="配置当前名字的任务和账号选项")
    parser.add_argument("--task", action="append", default=[], help="仅本次运行指定任务，不改保存的任务计划")
    parser.add_argument("--once", action="store_true", help="本次指定任务完成后退出并释放控制权，保留 Android；需配合 --task")
    parser.add_argument("--task-options", type=parse_task_options, help='本次任务选项 JSON，例如 {"备战副本":{"免费接力":true}}；需配合 --task')
    mode.add_argument("--prepare", action="store_true", help="初始化运行文件，不启动 Android 或游戏")
    mode.add_argument("--check", action="store_true", help="准备并检查 Android 连接，不运行游戏任务")
    mode.add_argument("--stop", action="store_true", help="关闭该实例窗口及 Waydroid 后台，保留配置和账号数据；请先退出同名脚本")
    args = parser.parse_args()
    # 明确覆盖继承值，避免其它名字从后台启动者那里继承无窗口策略；子进程恢复沿用本次选择。
    os.environ["MR3A_SHOW_WINDOW"] = "0" if args.no_window else "1"
    if args.once and not args.task:
        parser.error("--once 需要显式 --task")
    if args.task_options is not None and not args.task:
        parser.error("--task-options 需要 --task")
    if args.task and (args.prepare or args.check):
        parser.error("--task 不能与 --prepare 或 --check 同时使用")
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
    with session.control() as control_fd, ExitStack() as temporary_files:
        registry.prepare(session.spec)
        temporary_tasks = None
        if args.task_options is not None or args.once:
            try:
                temporary_tasks = build_task_config(
                    load_task_interface(session.spec.work_root / "interface.json"),
                    json.loads(session.spec.config_path.read_text()), args.task, args.task_options if args.task_options is not None else {},
                )
            except ValueError as exc:
                parser.error(str(exc))
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
        if temporary_tasks is not None:
            if "--task-config" not in support.stdout:
                raise RuntimeError("共享 MaaPiCli 尚未支持临时选项，请重编本地定制版本")
            task_file = temporary_files.enter_context(tempfile.TemporaryFile(mode="w+", encoding="utf-8"))
            task_file.write(json.dumps(temporary_tasks, ensure_ascii=False))
            task_file.flush()
            task_file.seek(0)
            os.set_inheritable(task_file.fileno(), True)
            command.extend(["--task-config", f"/proc/self/fd/{task_file.fileno()}"])
        else:
            for task in args.task:
                command.extend(["--task", task])
        env = session.environment()
        env["MR3A_PICLI_PID"] = str(os.getpid())
        print(f"运行实例 {session.spec.name}：{session.spec.work_root}", flush=True)
        if args.once:
            from runtime.one_shot import run_once
            result = run_once(
                command, cwd=session.spec.work_root, env=env,
                pass_fds=(control_fd, task_file.fileno()),
            )
        else:
            os.chdir(session.spec.work_root)
            os.execve(binary, command, env)
    print("MR3A_RESULT " + json.dumps(result, ensure_ascii=False), flush=True)
    return result["exit_code"]


def _exit_on_signal(signum, frame):
    del frame
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _exit_on_signal)
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
