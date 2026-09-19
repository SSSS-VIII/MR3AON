# 游戏闪退后重启 Waydroid，而不是每次启动都重启

## 需求

游戏进程消失时应把 Waydroid session 拉起来再继续。正常启动、主动关游戏、错误恢复里的 `StopApp` 不能当成闪退。

## 改动

StartApp 成功并关掉启动节点之后，`ArmGameProcessWatch` 才开始监视。Context sink 大约每 5 秒 `pidof` 一次，不另开线程，也不在 sink 里 `post().wait()`。第一次 `pidof` 成功记为见过活进程；之后连续两次找不到，才置 `waydroid_restart_requested`。

`处理游戏闪退` 只在这个标志为真时命中。它放在 `启动流程` 和 `Default_on_error` 的 next 最前。启动任务里转到 `RestartWaydroid`：停 session、后台再开、重连 ADB、设回 `1280x720`、`show-full-ui`，然后重新 `启动应用`。业务任务里把当前任务交还调度，不在回调里直接重启。

主动关闭前先 `DisarmGameProcessWatch`：`关闭游戏` 的「开始关闭游戏」、启动失败分支，以及 `RestartGame` 在 `StopApp` 之前。避免停进程后的空 `pidof` 再触发一轮 Waydroid 重启。

## 验证

- `tests/test_game_process_watch.py`：未监视、还没见过活进程、连续 miss、中途又出现、disarm、恢复只触发一次。
- `启动游戏.json`、`关闭游戏.json`、`Default_on_error.json` 可解析。
