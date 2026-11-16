# 领取饭团登记到下一个 05:00

## 现象 / 需求

领取饭团跑完就离开队列，跨过 05:00 不会再排进来。需要和其他日常任务一样，完成后禁用到下一个 05:00。

## 原因

`领取饭团回到了主页面` 直接 `StopTask`，没有调用 `SetManagedTaskPersistentState`。

## 改动

该节点改为对 `领取饭团entry` 写入 `enabled: false`、`valid_until: next_daily_reset`，下一节点再 `StopTask`。

## 验证

- `tests/test_pipeline_guards.py` 中领取饭团的完成登记断言通过。
- 未在设备上跨过 05:00 实跑。
