# 只运行启动游戏后的 TUI 与子进程收尾

## 现象 / 需求

用户此前多次遇到任务结束后 MaaPiCli、虚拟环境 Python 或 TUI 未正确退出，要求在主环境研究只跑「启动游戏」时的收尾。

## 原因与排查证据

- 启动流水线命中「启动游戏到了主页面」即执行 StopTask。只有这一项时，Agent 队列无后续或延后任务，通知 queue_finished，不应进入长期 Wait，也不执行「关闭游戏」。
- 原代码在 TUI 退出后无条件向 PiCli 发 SIGINT，再同步调用可能卡住的 AgentServer.shut_down，最后 os._exit；这是强制退场，不能保证终端/日志队列正常清理。
- MaaPiCli 则在断开 Agent 后立即返回，boost::process::child 析构会终止尚未退出的 Agent。Agent 的父死信号也可能先于 Textual 终端恢复和 Python 收尾生效。
- 修复前主环境真实 `./run main --task 启动游戏` 约一分钟结束，进程、控制锁及本次 socket 没有残留，配置内容未变化，但终端出现 8 个 leaked semaphore 警告。独立无点击夹具进一步复现 TUI 未输出退出备用屏序列，说明「进程没了」不代表 TUI 正常收尾。

## 改动

- MaaPiCli 断开 Agent 后等待子进程正常退出，最多八秒才终止并回收；让 Textual 退出和 Python 日志队列释放有机会完成。
- TUI 正常完成/断开后先恢复终端，等待客户端断开，不抢先杀 PiCli；正常路径返回解释器完成清理，不再无条件 os._exit。
- q 退出使用本地定制 PiCli 的 SIGUSR1 停止请求：信号处理器仅置标志，Runner 在自身循环中 post_stop，保留控制器、Agent 和任务的正常析构路径。Agent 只向当前实例绑定的 PID 发请求；不缓存回调作用域中的远程 Tasker 句柄跨回调使用。
- native shut_down 在 daemon 线程执行，等待最多两秒，清理当前 socket；异常/超时保留强制退出兜底。等待客户端断开最多五秒，超时才尝试结束绑定 PiCli。SIGINT/SIGTERM 的旧紧急退出机制未修改，不将强杀、硬断电等异常路径宣称为正常退出。
- `.venv` 是共享依赖目录，应该保留；需要结束的是其中运行的 Agent Python 及资源跟踪进程。完成启动游戏后，游戏与 Waydroid 继续运行，释放 Android 用显式 `run [名字] --stop`。
- 两个仓库需配套使用，本机 MaaPiCli 已重新编译，共用程序软链接不变；MaaPiCli 提交 `d3a63fd5`，其代码与双语开发说明同次提交，本记录随 MR3A 配套修复提交。

## 验证

- 4 项实机只读退出回归通过：headless、TUI 自动完成、零延迟完成、运行中 q。检查退出码、正常 Agent 关闭日志、备用屏退出序列、termios 恢复、无 semaphore 警告和无本实例残留子进程；测试不向游戏点击，主环境原配置不替换。
- 4 项关闭单测通过：native 关闭成功、抛错、卡住超时、只向绑定 PID 发送停止请求；结合硬失败/路径保护共 17 项通过。
- 全量普通回归：128 passed、5 skipped、5 failed、79 subtests passed。5 项仍为既有悬赏路径/旧节点与 enable/ enabled 兼容断言失败；实机测试默认跳过，不以修改旧断言掩盖失败。
- MaaPiCli 原 3 项运行目录/错误控制器测试通过，重新构建成功，两个仓库 diff 检查通过。
- 修复后再次执行真实 `./run main --task 启动游戏`：退出码 0，备用屏和 termios 恢复，无 semaphore 警告；无 main 实例残留进程，本次 socket 不存在，控制锁释放，主配置与排查前散列完全一致（原 17 项计划保留）。main 和 xiaoli 的 Android 会话均保持 RUNNING，游戏仍在 main 前台。
- 原主配置不重写，不运行后续日常，不清理未完成鬼族或 MaaUtils 的原有改动。真实 TUI 输出含配置选项，仅存本地忽略提交的私有 debug 日志，不写入记录或测试报告。
