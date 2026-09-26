# 家族战：八点门槛与完成后日更禁用

## 现象 / 需求

家族战已有周末限制，但 20:00 前在流水线里挂机空转；完成后只 `StopTask`，可能当晚再进队。需要对齐 3v3 / 周末活动：未到点挂起调度，完成后登记禁用到下一 05:00。

## 改动

- 周六/日：原 `家族战当前时间小于20点` 改为 `ScheduleDeferredTask` `daily_times=["20:00"]`。
- 成功结束、未报名、非周末、已过 21:20：走 `登记家族战每日完成`（`next_daily_reset`）。
- 不改动 `常驻任务.json` 选项与文案，减少相对上游的差异。

## 验证

- `tests/test_pipeline_guards.py`：`test_family_war_defers_before_eight_and_registers_completion`。
- 下次周末实机：20 点前应挂起；完成后当晚不应再进。
