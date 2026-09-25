# Agent 运行时 Textual TUI（竖屏半窗）

## 现象 / 需求

纯日志观感差，需要可扩展的交互 TUI：完整任务列表（含 Agent 挂起未提交项）、当前任务与节点、底栏小动画。按 niri 半窗竖屏设计，风格参考 btop，不用大 ASCII 艺术字。

后续反馈：小人要走到尽头再回头；node 不要刷未命中的候选，next 轮询时显示父节点；waiting 要有三点跳动；按 `q` 退出 TUI 后 Agent/`./run` 要跟着结束。

## 原因

任务真实状态在 Agent 内存（队列 / 延后表 / 完成登记），终端此前只有 Loguru。maafw 控制台已关，不适合当仪表盘数据源。

原 TUI 在 Recognition `Starting` 就改 node，next 轮询里每个候选都会闪一下。退出时只 `shut_down`，`join` 偶发不返回，进程/父 PiCli 可能挂住。

## 改动

- 引入 Textual；`agent/tui/`：btop 深色主题、左任务列表、中当前任务/节点、底栏小人左右搬砖。
- `build_task_rows` 合并 `managed_task_queue`、`deferred_task_store`、持久化完成态；队列增加 `plan_order`。
- `TuiStatusSink`：识别 `Succeeded` / 动作 `Starting` 才更新命中节点；`NextList` Starting 显示父节点。
- waiting 状态后接 `●○○` 轮播；小人按舞台宽度走到尽头再回头。
- TUI 退出后 `shut_down`，`join` 超时则 `os._exit(0)`，并 `sys.exit(0)` 结束 Agent，便于 PiCli/run 收尾。
- Agent 在 TTY 下默认起 TUI（`MR3A_TUI=0` 可关）；控制台日志降到 ERROR，文件日志不变。
- `requirements.txt` 增加 `textual>=2.0`。

## 验证

- `test_tui_snapshot` 手工跑通。
- Textual `run_test` 生成预览图；退出路径需实机再确认 PiCli 是否随 Agent 退出。
