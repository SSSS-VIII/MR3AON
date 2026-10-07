# S/SS+ 完成登记持久化禁用

## 需求

S/SS+ 完成后与每日悬赏一样写入 Agent 持久化禁用，避免同一日内反复进队。

## 改动

- `S_SS+完成回到了主页面`：`StopTask` 改为 `SetManagedTaskPersistentState`（`entry: S_SS+entry`，`enabled: false`，`valid_until: next_daily_reset`），再进 `S_SS+完成停止任务`。
- `tests/test_pipeline_guards.py` 补上该成功路径断言。

## 验证

- unittest：`test_daily_completion_registration_is_only_on_explicit_success_paths` 通过。
