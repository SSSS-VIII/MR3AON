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

## 合并回退（同日）

误把上游「直接去巡逻 → 点兽文字/图片 + 空的没有通灵兽」合进来后：`没有通灵兽说明还在巡逻` 变成只有 `next` 的空节点，永远成功且**不登记倒计时**，后面的 2h `fallback_seconds=7200` 也走不到。已恢复本地：

- `直接去巡逻`：`timeout 5000` → `点击通灵兽`（侧栏绿幕模板）；`on_error` 仍为 OCR 倒计时登记 / 2h 保底。
- `没有通灵兽说明还在巡逻`：侧栏 OCR 时分秒 + `ScheduleDeferredTask`。
- 启动设置：`屏蔽所有组队邀请` ROI 高度改回 `201`；`设置页面上滑` 滑动改回 `1000,450→1000,400` + `post_delay 1000`，去掉上游上滑计数节点。
