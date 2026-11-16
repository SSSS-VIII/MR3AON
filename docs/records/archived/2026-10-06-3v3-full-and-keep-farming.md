# 3v3 满了也刷（接 Agent 调度）

## 需求

沿用原有「满了也刷（最好不要）」；挂到 `3v3entry`；每场回决斗场要能让 Agent 插队后再继续刷；超时登记并挂到次日 11:00。

## 原配置缺什么

- option 已定义，但 `3v3entry` 未挂 `option`，界面选不到。
- Yes 只把 `3v3每日任务满了` 的 next 改成继续匹配。
- 若只 `StopTask` 而不 `ManagedTaskSchedulerYieldCurrent`，当前 3v3 会从 Agent 队列消费掉，不会再回来刷。

## 改动

- `3v3entry` 挂上「满了也刷（最好不要）」。
- **底图接好边**，分支节点默认 `enabled: false`，Yes 时再打开：
  - `3v3每日任务满了` → `3v3满了也刷继续匹配`（关）/ `登记3v3每日完成`
  - `回到了3v3主页面` → `3v3满了也刷本场结束退出`（关，Yield→StopTask）/ `点击每日任务`
- Yes 时另 override：`没有匹配模式说明时间不符合` 的 action 改为 `SetManagedTaskPersistentState`（`next_daily_times` + `11:00`），替换原 `ScheduleDeferredTask`，避免双重入队。
- `SetManagedTaskPersistentState` 支持 `valid_until: "next_daily_times"`。

## 验证（待实机）

- 开「满了也刷」：每日「已领取」后继续匹配；打完回决斗场应让出并稍后再次进入 3v3。
- 非开放时段：登记禁用并挂到次日 11:00。
- 关：满了仍走 `登记3v3每日完成`（下一 05:00）。
