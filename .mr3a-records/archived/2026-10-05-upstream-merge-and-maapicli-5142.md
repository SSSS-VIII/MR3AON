# 上游合并 + 定制 MaaPiCli 对齐 v5.14.2

## 现象 / 需求

- 上游 `originalsage/MR3A` 有一批更新（关闭游戏/应用宝、邮件、悬赏、AGPL、`maafw==5.14.2` 等），需要合进 MR3AON。
- 合并后启动报 Agent 协议 mismatch：`client protocol=7`（DEBUG_VERSION 旧 MaaPiCli）vs `server protocol=8`（`maafw` 5.14.2）。
- 官方 release 二进制 **不能** 替代本机已改过的 `MaaPiCli`（`AgentSchedulerBootstrap` 等调度逻辑）。

## 原因

- 上游把 Python binding 升到 5.14.2 / 协议 8；本机 `deps/bin/MaaPiCli` 仍指向自编译旧产物（约 5.12 线）。
- 冲突流水线若整文件用 upstream，会丢掉 fork 的持久化登记、红点、总超时等；应本地为底、重叠 bug 修法跟上游。

## 改动

### 合并策略（`4284999`）

- 以本地流水线为底；两边同修的识别/滑动/ROI 等跟 upstream。
- 保留 fork：Agent 调度相关、`SetManagedTaskPersistentState` / `StopTask`、战令红点、`aspect_ratio` 的 adb `wm size` 检查、README MR3AON。
- 主要冲突文件：启动游戏、家族祈福、每日商店、通灵巡逻、领取战令、领取饭团。

### MaaPiCli

- `mr3a-managed-queue` merge `v5.14.2`，`./dev/build.sh`（`WITH_KWIN_CONTROLLER=OFF`）重编。
- Fedora 需 `pipewire-devel`、`libei-devel`（v5.14 的 LinuxControlUnit 强依赖 PipeWire）。
- `deps/bin/MaaPiCli` 继续软链到 `/home/linn/MaaPiCli/build/bin/RelWithDebInfo/MaaPiCli`；误下的官方 `deps/maa-v5.14.2` 已删。

### 本机状态

- 合并后流水线完成登记路径有变动，已清空 `deps/bin/config/agent_task_state.json` 与 `deps/.run-test/config/agent_task_state.json`（空 `tasks`/`nodes`），避免旧禁用状态挡住重跑。

## 验证

- 自编译 `libMaaAgentClient` 与 `.venv` `maafw` 均为 v5.14.2。
- 启动应不再出现 protocol 7/8 mismatch；再跑 `./run` 确认 Agent 连上并重新登记日常。
