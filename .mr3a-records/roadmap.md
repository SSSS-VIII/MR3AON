# Roadmap

已完成错误恢复重构：默认错误与普通 `back` 分流；全局恢复回主页后每个 task 最多重试一次；重启使用启动 task 记录的实际包名；恢复耗尽后停止整个 Tasker。

已修复藏宝图等待进入 fight 的节点：用 `inverse` 等待 `进入战斗中.png` 消失，存在时按 `rate_limit: 2000` 重试，消失后才进入 `fight`；默认 timeout 显式设为 30 秒。相同的“清自己藏宝图”分支同步修复。

task/重复节点的通用无进展 watchdog 与 `进入战斗中.png` 页面上下文联合识别仍未采用；当前已知误匹配会在后续 `fight` 全 miss 后由 timeout 接入全局恢复。

已为启动流程接入现有 `LoopDeadline`总时限：正常启动 6 分钟后走原有关闭游戏重试，业务任务的恢复启动 2 分钟后再次 `RestartGame`。该时限使用 Agent 单调时钟，不会被节点持续识别成功或 JumpBack 重置。

后续继续使用临时 MaaPiCli 副本做真实设备验证，正式入口缓存不动。

已实现 Agent 接管 MaaPiCli 任务队列的延后任务调度试点：MaaPiCli 只提交一个
bootstrap，Agent 将每个业务任务作为独立顶层 task 逐项提交。业务流水线即将执行
`StopTask` 时由 context sink 先提交下一项；自然返回则由 wrapper 尾部 finalize 兜底。
真实 MR3A interface 已验证 `启动游戏 -> 领取饭团 -> 小屋修炼 -> AgentSchedulerWait`
连续执行；小屋 OCR 到 `随机访问20小时02分` 后登记到期时间并退出，Agent 保持等待。
已扩展到通灵巡逻、忍村试炼、藏宝图和 3v3：通灵巡逻按实际倒计时或 2 小时估值挂起；忍村试炼每 4 小时挂起并记录历史最大挑战次数；藏宝图连续运行 1 小时后在安全节点一次性让出；3v3 因时间未开放退出时，无视 OCR 内容按每日 13:00/20:00 固定时点挂起。

2026-08-29 长时运行确认 Agent 主队列整体能够持续工作，但发现两个配置/恢复问题：活动配置遗漏 3v3；藏宝图刷新冷却节点的一小时让出检查缺少未命中兜底，造成 30/60 秒超时交替重启。3v3 已恢复到本机活动配置；藏宝图已补 `藏宝图None` 末端兜底。

全局恢复已改为使用 MaaFramework 原生 `Context.run_task()`：在继承 pipeline override、共享 TaskState 的新 Context 中用空 JumpBack 栈恢复当前业务入口，完成后 finalize 调度并停止外层旧任务，不再依赖框架修改清理 JumpBack。

待下次实机长时运行验证：藏宝图跨刷新冷却持续刷取、重启恢复不再继承错误路径，以及 3v3 到 13:00/20:00 的固定时点重排。

Agent 启动终端的大块乱码已确认是截图头被 Waydroid `amdgpu.ids` 警告污染后，MaaFramework 将 PNG 二进制作为 Error 输出。不修改框架，本机运行配置关闭框架 stdout，日志仍写文件；Agent 另外禁用 MaaPiCli 子进程中的 ANSI 颜色，并用 `realpath` 修复 build 软链接下的项目根识别。

3v3 跑酷点击时序已增加 ADB 耗时校准：保留首段 500ms 校准，每次点击再扣除 38ms；不足部分作为序列内欠账由后续间隔偿还，避免长点击序列持续累积 ADB 往返耗时。
