# 测试环境

## 项目

- 项目目录：`/home/linn/MR3A`
- 设备连接：Waydroid + ADB
- 启动入口：仓库根目录 `./run`。它先准备 Waydroid / ADB，再执行 `deps/bin/MaaPiCli -d`
- 测试入口：`./run test`。工作目录是 `deps/.run-test`（已在 `deps/*` 忽略里）。配置、`maafw.log`、Agent 自定义日志和 `agent_task_state.json` 都写在这里，不回写 `deps/bin/config` 和 `debug/`
- `deps/bin/MaaPiCli` 保持指向 `/home/linn/MaaPiCli/build/bin/RelWithDebInfo/MaaPiCli` 的符号链接，不改成包装脚本
- 正式入口缓存：不修改、不覆盖
- 运行验证：优先使用临时 MaaPiCli 副本，避免污染主入口配置

## 2026-08-27 错误恢复重构验证

- Python：3.14.6
- MaaFramework Python binding：5.12.2
- 虚拟环境：`/home/linn/MR3A/.venv`
- 已执行：全部资源 JSON 解析、Python `compileall`、恢复链静态断言、7 个错误恢复/流水线保护单元测试、MaaFramework `Resource.post_bundle` 整包加载、`git diff --check`
- 本次未启动正式 `maapicli`，未执行真实设备重启，未修改运行缓存

## 关键验证命令

```bash
PYTHONPATH=agent ./.venv/bin/python -m compileall -q agent tests
PYTHONPATH=agent ./.venv/bin/python -m unittest -v tests/test_error_recovery.py tests/test_pipeline_guards.py
PYTHONPATH=agent ./.venv/bin/python tools/ci/check_resource.py assets/resource
git diff --check
```

## 独立 Waydroid（2026-11-01）

保留 RPM Waydroid 1.6.3，主实例仍使用普通 `waydroid` 命令和 ADB server 5037。次实例使用仓库启动适配层，无需自行构建 Waydroid。

```bash
# 桌面普通用户执行；首次自动 sudo 创建实例，再启动独立容器和窗口
./tools/waydroid-instance --slot 1 start
./tools/waydroid-instance --slot 1 status

# 首次 Android 启动后，授权本机用户 ADB 公钥（不修改主 Android）
sudo ./tools/waydroid-instance --slot 1 authorize-adb
./tools/waydroid-instance --slot 1 adb connect
adb -P 5038 devices

# 仅停止次实例，保留数据；下次仍用 start
./tools/waydroid-instance --slot 1 stop
```

当前 slot 1 已创建并授权，IP 为 `192.168.241.112:5555`（以 status 为准），分辨率 1280x720。`adb -P 5038 -s <地址> shell ...` 控制次实例；不带 `-P` 的 adb 仍控制主 server。

系统数据/日志在 `/var/lib/waydroid-mr3a1/`，Android 用户数据在 `~/.local/share/waydroid-mr3a1/android-data/`。systemd 日志分别用 `journalctl -u mr3a-waydroid-1` 与 `journalctl --user -u mr3a-waydroid-session-1` 查看。两个服务按需创建，主机重启后手动 start 即可；主机重启场景尚未实测。

适配目前限定已验证的 1.6.3，软件包版本变化需重新核对；更新共享 Android 镜像前先停止次实例。仅 Waydroid 双开已落地，MR3A 多实例运行目录接入尚未完成，不能直接认为两份脚本已可安全并跑。
