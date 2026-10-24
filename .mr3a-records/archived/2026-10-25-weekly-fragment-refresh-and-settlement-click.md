# 每周逆袭残卷刷新 + 悬赏结算点确定

## 现象 / 需求

1. **每周逆袭列表刷新**：刷新按钮有 CD；可用「残卷兑换」进出绕过且不改筛选。需要任务选项可切，默认仍是右上角刷新。
2. **结算误弹详情**：`结算确定` 用大块 DirectHit `[521,408,246,309]` 随机点，常点到奖励图标弹出「查看详情」，挡住「确定」后战斗链空转。

## 残卷刷新链路

- 任务选项改为 switch `残卷兑换进出刷新`（默认 No）：Yes→残卷路径，No→右上角刷新；label 写明 Yes/No 含义。override `每周逆袭悬赏执行刷新.next`。
- `每周逆袭悬赏残卷兑换刷新`：先 OCR 列表页「刷新」再硬点残卷坐标（禁止 DirectHit 盲进）。
- 进店确认：大块标题模板
  - `每周逆袭残卷兑换标题.png`
  - `每周逆袭悬赏令商店标题.png`
  （截图实测 OCR「残卷兑换」常读成繁体错字，不用 OCR replace。）
- 点返回 → ColorMatch 等到黑屏出现 → `inverse` 等到黑屏结束 → 立刻 `每周逆袭悬赏点击刷新后狂点加入队伍`（×8）回核心。
- 不写抢点枢纽 / 盲点加入；也不做「查看详情」专项处理。

## 结算确定

以下节点由 DirectHit 大 ROI 改为同 ROI OCR「确定|下一页」后 `Click` 命中框：

- `S_SS+悬赏结算确定`
- `每日悬赏结算确定`
- `每周逆袭悬赏悬赏结算确定`
- `每日逆袭悬赏刷出A结算确定` / `悬赏结算确定` / `清A结算确定`

截图节点仍先 `SaveRewardScreenshot`，再进上述确定节点。

## 验证

- `tests.test_pipeline_guards.PipelineGuardTest.test_weekly_bounty_refresh_mode_button_default`
- `tests.test_pipeline_guards.PipelineGuardTest.test_bounty_settlement_screenshots_use_30s_burst_gap`
- 标题模板对残卷店 / 悬赏令店 / 列表页的 TemplateMatch 区分（离线截图）

## 提交

- `768d2c4` fix: 每周逆袭残卷刷新按页确认；悬赏结算改点 OCR 命中框

## 上游注意

- 合并时勿把结算确定改回大块 DirectHit。
- 残卷路径：认刷新 → 点残卷 → 模板确认店 → 黑屏出现 → 黑屏结束 → 狂点×8；热路径仍不要挂让出检查。
