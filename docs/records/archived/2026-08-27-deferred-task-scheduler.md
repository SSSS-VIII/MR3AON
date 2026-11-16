# Agent 延后任务调度试点

## 目标语义

- 业务流水线识别倒计时后正常退出，不在 pipeline 内轮询。
- Agent 保存 `key / entry / due_at / pipeline_override`；定时器到期只修改内存状态。
- 每个普通任务完成后，已到期任务优先于 MaaPiCli 原队列的下一项。
- 同 key 再次登记会取消并覆盖旧定时器。

## 最终结构

MaaPiCli 在存在 Agent 时不再预先提交全部任务，而是把已解析的任务计划交给唯一的
`AgentSchedulerBootstrap`。Agent 保存普通队列，并把每个业务任务作为独立的顶层
task 逐项提交；没有使用嵌套 `context.run_task()`，因为实测嵌套任务里的自定义动作
只能拿到外层 bootstrap 的 task 上下文。

每个业务 task 使用 wrapper 进入真实入口。流水线即将执行 `StopTask` 时，context sink
会在 `Node.Action.Starting` 阶段通知调度器，先提交到期插队项或下一普通项，再允许当前
task 结束。对于不执行 `StopTask` 而自然返回的流水线，wrapper 尾部 finalize 负责同样的
推进。全部普通任务和延后项耗尽后，MaaPiCli 按原有 `wait()` / `running()` 逻辑退出；
Runner 不使用空闲宽限或固定延时。

MaaPiCli 任务选项生成的 `pipeline_override` 是对象数组；Agent 会按顺序深合并为对象，
再与 wrapper 节点一起提交给 Tasker。

## 小屋修炼接入

- `忍者小屋还在修炼` 的 OCR 动作登记 `小屋修炼entry`。
- 支持 `天 / 小时 / 时 / 分钟 / 分 / 秒` 组合解析，并增加 5 秒余量。
- 延后任务仍识别到倒计时时，会用新时间覆盖同一个 `小屋修炼` 挂起项。

## 验证

使用 `/tmp` 中的 MaaPiCli 和临时配置，通过 MR3A 的真实 interface 连接 Waydroid；
未读取用户配置，也未使用自编测试用例。执行顺序为：

- `启动游戏`（task_id `200000002`）在“启动游戏到了主页面”的 `StopTask` 前提交
  `领取饭团`（task_id `200000004`）。
- `领取饭团` 在“领取饭团回到了主页面”的 `StopTask` 前提交 `小屋修炼`
  （task_id `200000005`）。
- 小屋 OCR 得到 `随机访问20小时02分`，登记延后任务到
  `2026-08-28 20:53:14`，退出前提交 `AgentSchedulerWait`（task_id `200000006`）。
- 游戏进程 PID `1765` 在整轮验证中保持不变，Android crash buffer 为空。

测试后已主动停止临时 MaaPiCli，未让等待 task 在后台持续 20 小时。

## 待真机验证

- 用较短的小屋倒计时确认到期后在两项普通任务边界优先执行领取入口；普通队列为空时
  则由等待 task 到期后直接提交。
- 确认延后领取后再次出现倒计时时会覆盖旧状态，而不是产生重复任务。
