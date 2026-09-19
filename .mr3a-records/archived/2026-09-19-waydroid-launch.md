# 启动前把 Waydroid 拉到可看、可识别的状态

## 现象

直接跑 MaaPiCli 时，Session 显示 RUNNING 但 Container 是 FROZEN，`adb shell getprop` 会挂住。`session start` 即使成功也不开窗口，niri 上看不到画面。设备物理分辨率不是 16:9，脚本识别会偏。

## 原因

MaaPiCli 连控制器在 Agent 启动之前。容器冻结时不能把 Session RUNNING 当成已经可用。`session start` 只拉起会话，窗口要另外 `show-full-ui`。脚本工作分辨率是覆写后的 `1280x720`，不是物理尺寸。

## 改动

仓库根目录 `./run` 先调用 `ensure_waydroid_and_adb()`，再 `cd deps/bin` 执行现有的 `./MaaPiCli -d`。`deps/bin/MaaPiCli` 仍是指向构建产物的符号链接，不在这里包一层。

`ensure_waydroid_and_adb` 与闪退恢复用的 `restart_waydroid_session` 同一套收尾：

- Container 为 FROZEN 时先 `session stop`，再后台 `session start`（该命令会占住前台）。
- `waydroid adb connect` 之后等到 `sys.boot_completed=1`。
- `adb shell wm size 1280x720`。已经是这个 Override size 就跳过。
- `waydroid show-full-ui`。本机有 niri 时按窗口 App ID `Waydroid` 聚焦。

不使用 `EnsureWaydroidReady` 流水线节点，也不靠 root 做 `container unfreeze`。

## 验证

- 容器处于 FROZEN 时执行 `./run`，session 重新拉起，`boot_completed=1`，进入主页面。
- `show-full-ui` 之后 niri 上出现 Waydroid 窗口并被聚焦。
- `wm size` 确认 Override size 为 `1280x720`。
