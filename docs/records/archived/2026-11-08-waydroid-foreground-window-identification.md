# 两个前台Waydroid窗口归属核对

## 现象与结论

用户反馈前台有两个Waydroid窗口，只认识main。2026-11-08 21:43只读核对niri窗口列表、命名注册表、实例状态和会话进程：

| 窗口 | 归属 | 位置 | 状态 |
| --- | --- | --- | --- |
| id=6，PID28248，标题Waydroid | main，slot0 | 工作区2 | RUNNING |
| id=77，PID2908091，标题Waydroid | arena，slot3 | 工作区3 | RUNNING |

arena的容器/会话进程于21:38:48启动，会话服务为 `mr3a-waydroid-session-3.service`；`.mr3a-instances/arena/instance.json` 明确登记名字arena、slot3。当前开发交接注明独立空白arena实例正在验证竞技场原客户端GameOnly入口，与额外窗口一致。两个窗口都只显示默认标题Waydroid，没有实例名，所以前台难以区分。

xiaoli(slot2)与small(slot1)均为STOPPED，额外窗口不是这两个实例。main与arena的数据按命名实例分开，仍共用程序和源码。

## 操作与边界

只查看窗口、进程、实例元数据、会话状态及开发记录。没有关闭窗口、停止实例、点击游戏或修改运行配置；arena可能正被其它开发验证使用。本次没有修改窗口命名或后台显示策略。
