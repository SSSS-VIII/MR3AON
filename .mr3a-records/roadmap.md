# Roadmap

已完成错误恢复重构：默认错误与普通 `back` 分流；全局恢复回主页后每个 task 最多重试一次；重启使用启动 task 记录的实际包名；恢复耗尽后停止整个 Tasker。

已修复藏宝图等待进入 fight 的节点：用 `inverse` 等待 `进入战斗中.png` 消失，存在时按 `rate_limit: 2000` 重试，消失后才进入 `fight`；默认 timeout 显式设为 30 秒。相同的“清自己藏宝图”分支同步修复。

task/重复节点 watchdog 与 `进入战斗中.png` 页面上下文联合识别暂未采用；当前已知误匹配会在后续 `fight` 全 miss 后由 timeout 接入全局恢复。

后续继续使用临时 MaaPiCli 副本做真实设备验证，正式入口缓存不动。
