# ./run test 使用独立工作目录

## 需求

测试启动不能改主环境的 `deps/bin/config`、`debug/` 和任务状态。

## 改动

`./run` 不加参数时仍进 `deps/bin`。`./run test` 在 `deps/.run-test` 放一份入口：复制 `MaaPiCli`，把同目录的 `.so` 用符号链接放进来。MaaPiCli 的用户目录取的是 `libMaaUtils.so` 所在目录，这样日志和配置才落在测试目录，而不是构建目录里指向主环境的链接。

`interface.json` 和 `resource` 仍指向仓库里的资源，只读。`config` 每次从主配置复制一份，之后只写副本。`MR3A_TEST_WORK` 让 Agent 的自定义日志和 `agent_task_state.json` 也写到这个目录。Agent 参数里的 `../../agent/main.py` 要求工作目录在 `deps` 下一级，所以目录是 `deps/.run-test`，不是仓库根或 `/tmp`。

`deps/*` 已被忽略，这个目录不会进 git。

## 验证

- `bash -n run` 通过。
- 设置 `MR3A_TEST_WORK` 后，任务状态路径落到该目录的 `config/agent_task_state.json`。
