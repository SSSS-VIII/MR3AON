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
