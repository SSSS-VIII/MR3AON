# Tasker 事件回调不能再发 Maa 请求

## 现象

2026-09-19 04:32，启动游戏认到主页面并执行 `StopTask` 后，队列停住，MaaPiCli 打印 `All tasks have been completed`。Agent 自定义日志停在「收到任务结束通知」，没有「调度已提交」。stderr 上是 ctypes 回调里的 `RecursionError`，出在 `dispatch_next` → `deepcopy`。

## 原因

不是 `pipeline_override` 越拷越深。Python 3.14 的 `RecursionError` 看的是 C 栈。Agent 等回包时，别的消息会在同一次 `send_and_recv` 里被处理。

Tasker / Controller / Resource 事件是 MaaPiCli 用 `send()` 塞进来的，对方并不等这次回调结束。`AspectRatioChecker` 挂在 Tasker 事件上，每次任务开始都访问 `tasker.controller`（以及截图、`post_stop`）。这次请求的回包 `_TaskerControllerReverseResponse` 会被内层等待读走，当成 `unexpected msg` 丢掉。外层那一帧不再返回，后面的回调都叠在它上面，直到 `deepcopy` 触发递归限制。

Context 事件、自定义动作、自定义识别不是这条路径。对方堵在 `send_and_recv` 里等我们回，再调 `get_node_data`、`tasker.stopping`、`post_task` 对得上。当前注册的 sink 里，会插进别的 RPC 的只有 `AspectRatioChecker`。`PopupWatchdog` 没有注册。

不改 MaaPiCli。

## 改动

- `AspectRatioChecker` 只读 `adb shell wm size`，不再调用任何 Maa API。有 Override size 时用覆写分辨率，否则用 Physical size。
- 比例不是 16:9 时只做标记。真正 `post_stop` 放在下一次 `dispatch_next`，那是对方正在等的调度回调。

## 验证

- `tests.test_scheduler_override`、`tests.test_pipeline_guards` 通过。
- `logical_display_size`：`Override size: 1280x720` 优先于物理分辨率；仅有 Physical size 时用物理值。
