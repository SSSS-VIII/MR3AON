# 每周逆袭悬赏：一小时安全点出让

## 现象 / 需求

`每周逆袭悬赏` 持续刷、无停止逻辑（任务描述也写了自行停）。希望和藏宝图一样：连续跑约一小时后，在安全页让出 Agent 调度，方便插队其它到期任务，然后再回来。

## 改动

- `_TIME_SLICE_SECONDS` 增加 `每周逆袭悬赏entry: 3600`（与藏宝图同机制，提交任务时 arm 让出信号）。
- 流水线安全点首项检查 `ManagedTaskYieldRequested` → `ManagedTaskSchedulerYieldCurrent` → 回主页 `StopTask`：
  - `每周逆袭悬赏悬赏主页面`
  - `每周逆袭悬赏悬赏仍在主页中`（未命中时走 `每周逆袭悬赏None` 兜底）
  - `每周逆袭悬赏悬赏进入战斗后回到了逆袭悬赏页面`
- **不**挂在 `每周逆袭悬赏点击刷新` 之后：刷新后要立刻狂点加入，打断会伤抢队。
- 任务描述改为说明一小时让出行为。

## 验证

- `tests.test_pipeline_guards.PipelineGuardTest.test_weekly_bounty_yields_only_from_safe_page_nodes`

## 上游注意

这一块（每周逆袭悬赏流水线 / 筛选与抢队核心环）后续上游可能有更新。合并时优先核对：

- 上述三个安全点的 `next` 是否仍含 `每周逆袭悬赏检查让出调度信号`
- `_TIME_SLICE_SECONDS["每周逆袭悬赏entry"]` 是否还在
- 不要把让出检查加回「点击刷新 → 狂点加入」热路径
