# Roadmap

已完成错误恢复重构：默认错误与普通 `back` 分流；全局恢复回主页后每个 task 最多重试一次；重启使用启动 task 记录的实际包名；恢复耗尽后停止整个 Tasker。

已修复藏宝图等待进入 fight 的节点：用 `inverse` 等待 `进入战斗中.png` 消失，存在时按 `rate_limit: 2000` 重试，消失后才进入 `fight`；默认 timeout 显式设为 30 秒。相同的“清自己藏宝图”分支同步修复。

task/重复节点 watchdog 与 `进入战斗中.png` 页面上下文联合识别暂未采用；当前已知误匹配会在后续 `fight` 全 miss 后由 timeout 接入全局恢复。

后续继续使用临时 MaaPiCli 副本做真实设备验证，正式入口缓存不动。

已实现 Agent 接管 MaaPiCli 任务队列的延后任务调度试点：MaaPiCli 只提交一个
bootstrap，Agent 将每个业务任务作为独立顶层 task 逐项提交。业务流水线即将执行
`StopTask` 时由 context sink 先提交下一项；自然返回则由 wrapper 尾部 finalize 兜底。
真实 MR3A interface 已验证 `启动游戏 -> 领取饭团 -> 小屋修炼 -> AgentSchedulerWait`
连续执行；小屋 OCR 到 `随机访问20小时02分` 后登记到期时间并退出，Agent 保持等待。
待倒计时较短时验证到期项在普通任务边界优先插入和实际领取流程。
