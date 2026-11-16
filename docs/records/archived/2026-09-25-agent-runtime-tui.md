# Agent 运行时 Textual TUI（竖屏半窗）

## 现象 / 需求

纯日志观感差，需要可扩展的交互 TUI：完整任务列表（含 Agent 挂起未提交项）、当前任务与节点、底栏小动画。按 niri 半窗竖屏设计，风格参考 btop，不用大 ASCII 艺术字。

后续反馈：小人要走到尽头再回头；node 不要刷未命中的候选，next 轮询时显示父节点；waiting 要有三点跳动并显示等待中的任务名；按 `q` 要直接回到 `linn@fedora:~/MR3A$`，不能停在 `./run`/MaaPiCli 会话里（不能再手动 Ctrl+C）。

## 原因

任务真实状态在 Agent 内存（队列 / 延后表 / 完成登记），终端此前只有 Loguru。maafw 控制台已关，不适合当仪表盘数据源。

原 TUI 在 Recognition `Starting` 就改 node，next 轮询里每个候选都会闪一下。`./run` 是 `exec MaaPiCli`：只关 Agent 时 PiCli 仍卡在 `wait(task)`；而且 `AgentServer.shut_down()` 常卡住，杀父进程的代码跑不到。Agent 也常被 systemd 收养，`getppid()` 并不是 MaaPiCli。手动 Ctrl+C 能退，是因为终端把 SIGINT 打到了仍占着 TTY 的 PiCli（`signal 2 received, exit`）。


## 改动

- 引入 Textual；`agent/tui/`：btop 深色主题、左任务列表、中当前任务/节点、底栏小人左右搬砖。
- `build_task_rows` 合并 `managed_task_queue`、`deferred_task_store`、持久化完成态；队列增加 `plan_order`。
- `TuiStatusSink`：识别 `Succeeded` / 动作 `Starting` 才更新命中节点；`NextList` Starting 显示父节点。
- waiting：`●○○` 轮播，并展示最近到期任务名 + ETA（`build_waiting_hint`）。
- 小人按舞台宽度走到尽头再回头。
- TUI 退出：先按祖先/同会话/同 TTY 找到 `MaaPiCli`，发 `SIGINT`（与 Ctrl+C 相同；卡住则 SIGKILL），再短超时 `shut_down` 后 `os._exit(0)`。不再先 `shut_down` 再杀父进程。
- Agent 在 TTY 下默认起 TUI（`MR3A_TUI=0` 可关）；控制台日志降到 ERROR，文件日志不变。
- `requirements.txt` 增加 `textual>=2.0`。

## 验证

- `test_tui_snapshot`（含 waiting hint）。
- 实机：`q` 后应直接出现 shell 提示符，无需再 Ctrl+C。
