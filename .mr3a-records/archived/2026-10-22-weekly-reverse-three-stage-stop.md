# 每周逆袭悬赏：三段停判（S上限 → A掉落 → S掉落）

## 需求

「逆袭A和逆袭S」不再两边同时抢，改为固定三段：

1. 只刷 S，直到顶栏「已达到每日悬赏奖励次数上限」
2. 只刷 A，直到「概率掉落」消失（与每日逆袭刷出 A 同 ROI）
3. 再只刷 S，直到「概率掉落」消失 → 任务结束

每阶段只认自己的停判；若掉落在前段已没了，进后段会自然立刻完成。

## 改动

- `每周逆袭悬赏.json`：`任务检查模块` 走 `阶段1/2/3进行中`；切入阶段用 `NodeOverride` 切换筛选与 `需要刷逆袭*`。
- `限时活动.json`：默认「逆袭A和逆袭S」；仅 A / 仅 S 为对应子阶段（仅 S 上限后跳过 A 进阶段3）。
- 每日逆袭刷出 A：概率掉落优先于次数上限，ROI 与文案对齐「已达到每日悬赏奖励次数上限」。
- `tests/test_pipeline_guards.py`：筛选顺序与三段停判断言。

## 验证

- `test_weekly_bounty_filter_selects_wanted_before_deselect`
- `test_weekly_bounty_three_stage_stop_logic`
