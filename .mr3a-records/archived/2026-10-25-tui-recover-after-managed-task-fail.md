# 管理任务硬失败后 TUI 卡死

## 现象

流水线 error 耗尽 → `Task.Failed`（未走 `StopTask`）后：

- PiCli 可能已打印 `All tasks have been completed`
- Agent TUI 仍显示 `agent running`、节点停在失败处，退不掉

## 原因

队列推进只挂在 `StopTask` Starting。硬失败没有 `StopTask`，`dispatch_next` 不跑，Agent 连接仍在，`join` 不返回，TUI 收不到退出。Tasker 回调里不能直接 `post_task`（见 `2026-09-19-tasker-sink-ipc-stack`）。

## 改动

- `ManagedTaskQueue.abandon_current`：硬失败丢掉当前实例，不入休眠队列。
- `ManagedTaskHardEndSink`：`Failed` / 仍占坑的 `Succeeded` 时另开线程 `abandon` + `dispatch_next`；调度失败则 `request_tui_exit`（只 `app.exit`）。
- 运行中的硬失败路径**不**主动杀 PiCli；`request_tui_exit` 只关 Textual。
- `q` / TUI 正常退出后：`main` 里仍结束同 TTY 的 MaaPiCli 并 `os._exit`，否则 shell 回不来（`shut_down` 常卡住）。

## 验证

- `agent/tests/test_managed_task_hard_end.py`
- 实机：`q` 应回到 shell；硬失败应推进下一项或关掉 TUI。
