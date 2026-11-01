# Wait 睡醒 post 失败 → AbortTasker（任务“全部结束”）

## 现象

2026-10-28 22:14：等待约两小时后应提交「通灵巡逻」，TUI/PiCli 表现为任务全部结束。

同日 14:12 / 16:13 / 18:13 同一条 Wait→通灵 曾成功；不是日常逻辑突然改坏。

## 原因

MaaFW `Tasker::inited()` = resource 有效 **且** `controller_->connected()`。
Wait 睡醒在回调里 `dispatch_next` → `post_task` 时：

```
[ERR] Tasker.cpp] Tasker not inited
```

→ 返回无效 `job_id` → Wait custom action `success=false` → `Default_on_error`
→ `RetryCurrentTaskAtHome` / `RestartGame` 对 `AgentSchedulerWait` 无法取回业务任务
→ `AbortTasker` 主动停队。

随后才出现 `connection lost, re-connect`（on_error 截图触发），说明睡醒当下控制器已断；长睡约 2h 后 ADB 掉线，第一次撞上这条路径。

次要问题：即便控制器正常，在仍占用 Tasker 的 Wait 回调里 `post_task` 也不该依赖；业务任务结束应走 `StopTask` + sink。

## 修复

- 提交 Wait 时带 `next: AgentSchedulerWaitStop`（`StopTask`）。
- Wait 睡醒只改道 Stop，由 `ManagedTaskStopSink` 再 `dispatch_next`（避免失败时走 `Default_on_error`→Abort）。
- 单测：`test_all_disabled_candidates_enter_wait_instead_of_finishing`。

说明：若睡醒时控制器仍断连，StopSink 的 `post` 仍会失败，队列可能停住；那是 ADB 长连稳定性问题，与本次 Abort 级联分开。需重启 Agent 加载新代码。

## 2026-11-01 工作区核对

正常路径和对应单测已经改为 StopTask；但 `override_pipeline` 抛异常时仍有直接 `dispatch_next(context.tasker)` 的兜底，与「不在 Wait 回调直接 post」的约束不一致，尚待处理。提交 Wait 时原本已附带 Stop 节点，异常策略需结合此事实核实。本轮相关单测通过，不代表长睡断连问题已经解决。

2026-11-01：重新执行 `test_all_disabled_candidates_enter_wait_instead_of_finishing` 通过。该功能与对应单测、记录独立提交，不包含鬼族等无关改动。
