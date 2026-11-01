# 同一 MaaPiCli 二进制支持独立运行目录

## 现象 / 需求

命名实例必须共用程序与源码，旧 CLI 根据动态库目录读取 PiCli 配置和写日志，换 cwd 无法完整隔离。单任务调试也不应再复制程序和配置。

## 原因

本地定制 MaaPiCli 的 main 把 user_path / resource_path 均固定为 library_dir；原 tools/run-* 为规避此约束复制二进制，且每次覆写测试配置。

## 改动

- 在 `/home/linn/MaaPiCli` 增加 `--user-dir` 和 `--resource-dir`，省略时保持原行为，不改变框架/Agent 协议。
- 增加 `--task`，只在当前 Interactor 内存中选择任务，已有任务选项原样保留；未知任务在连接控制器前返回错误，不覆盖保存的计划。
- 增加 CLI help、参数错误检查、中英文说明和不连接设备的验证脚本。增量重编同一份 MaaPiCli；MR3A 的正式二进制软链接保持原样。
- MaaUtils 原有未提交子模块状态未纳入本次提交。该功能在 MaaPiCli 仓库独立提交，MR3A 入口接入另作功能提交。

## 验证

- `cmake --build build --config RelWithDebInfo --target MaaPiCli --parallel 4` 成功。
- `python3 dev/test_runtime_cli.py`：两个独立目录共用同一二进制，各自创建 maa_option，任务选择后退出不修改配置内容；缺失参数值报错，无设备连接。
- MR3A 侧已验证非法任务在执行前返回 2，配置内容保持不变。未启动主游戏任务，也未更改主账号任务计划与登录凭据。

MaaPiCli 独立功能提交：`7fa3bf2c`。
