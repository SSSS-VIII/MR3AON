# Agent 运行时 Textual TUI（竖屏半窗）

## 现象 / 需求

纯日志观感差，需要可扩展的交互 TUI：完整任务列表（含 Agent 挂起未提交项）、当前任务与节点、底栏小动画。按 niri 半窗竖屏设计，风格参考 btop，不用大 ASCII 艺术字。

## 原因

任务真实状态在 Agent 内存（队列 / 延后表 / 完成登记），终端此前只有 Loguru。maafw 控制台已关，不适合当仪表盘数据源。

## 改动

- 引入 Textual；`agent/tui/`：btop 深色主题、左任务列表、中当前任务/节点、底栏小人左右搬砖。
- `build_task_rows` 合并 `managed_task_queue`、`deferred_task_store`、持久化完成态；队列增加 `plan_order`。
- `TuiStatusSink` 推当前节点；调度动作更新当前任务与 agent phase。
- Agent 在 TTY 下默认起 TUI（`MR3A_TUI=0` 可关）；控制台日志降到 ERROR，文件日志不变。
- `requirements.txt` 增加 `textual>=2.0`。

## 验证

- `test_tui_snapshot` 手工跑通。
- Textual `run_test` 生成预览图；未用 PiCli 长跑实机验收界面。
