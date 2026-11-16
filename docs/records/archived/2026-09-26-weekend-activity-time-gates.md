# 周末活动：九点门槛与失败一小时挂起

## 现象 / 需求

周末清晨会进「周末活动」，但活动入口（如多人竞速）未开放时 OCR/超时走 `Default_on_error` → `重启游戏`，立刻重排同一任务，饿死其它日常。需要按时间两层兜底：仅周末进入；九点前挂起到 09:00（同 3v3 `daily_times`）；失败再挂起一小时。

## 原因

流水线只有 `IsTargetWeekday`，没有开放时刻与失败退避。超时默认进全局恢复并 `RestartGame`，打断任务被立刻放回队首。

## 改动

- `周末活动当前为周六/日` 后先 `TimeBefore 09:00` → `ScheduleDeferredTask` `daily_times=["09:00"]`，再进集会所。
- 入口 `ResetCount` 后 `NodeOverride`：本任务内 `Default_on_error` 末项由 `重启游戏` 改为 `周末活动任务出错`（仍先闪退/回主页）。
- `周末活动任务出错`：`fallback_seconds=3600` 挂起后 `StopTask`。
- 成功完成与「非周末跳过」均 `SetManagedTaskPersistentState`（`next_daily_reset`），保留下一周期候选：周六做完后周日 05:00 可再进；平日跳过后当天不再反复进队检查。

## 验证

- `tests/test_pipeline_guards.py`：`test_weekend_activity_defers_before_nine_and_on_failure`、完成登记列表含 `登记周末活动每日完成`。
- 下次周末实机：凌晨应挂起到九点；九点后失败应约一小时后再进，其它日常可继续；周六完成后过夜到周日 05:00 应再跑周末活动。
