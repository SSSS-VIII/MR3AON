# 测试环境

## 项目

- 项目目录：`/home/linn/MR3A`
- 设备连接：Waydroid + ADB
- 正式入口：`maapicli`
- 正式入口及其缓存：不修改、不覆盖
- 运行验证：优先使用临时 MaaPiCli 副本，避免污染主入口配置

## 本次架构验证

- Python：3.14.6
- MaaFramework Python binding：5.12.2
- 虚拟环境：`/home/linn/MR3A/.venv`
- 已执行：全部资源 JSON 解析、Python `compileall`、fallback 链断言、`RestartGame` 控制器 mock 测试、`git diff --check`
- 本次未启动正式 `maapicli`，未执行真实设备重启，未修改运行缓存

## 关键验证命令

```bash
PYTHONPATH=agent ./.venv/bin/python -m compileall -q agent
PYTHONPATH=agent ./.venv/bin/python -c 'from custom.action import RestartGame; print(RestartGame.__name__)'
git diff --check
```
