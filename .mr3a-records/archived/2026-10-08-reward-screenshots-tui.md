# 结算 / 神秘商店截图与 TUI 浏览

## 现象 / 需求

悬赏类结算确认前要留图备查；神秘商店每次「自动刷新」回八格列表时截整页。Agent TUI 里能浏览这些图。

## 改动

- 自定义动作 `SaveRewardScreenshot`：按 `dir` 写入 `debug/reward_shots/<dir>/`，登记并做日常 05:00 周期外清理；目录名允许 `+`（如 `S_SS+`）。
- 流水线：每日悬赏 / S_SS+ / 家族战在原「结算确定」前插入同 OCR 截图节点，再 DirectHit 点确定；神秘商店进店与刷新回列表时截整页。
- TUI：当前任务面板下方奖励区，仅 Kitty TGP 单图；`d` 打开目录 OptionList，←/→ 翻图；非 Kitty 只提示不支持。依赖 `textual-image[textual]`。

## 验证

- `pytest agent/tests/test_reward_shots.py agent/tests/test_ansi_image.py`
- 实机 Kitty 下浏览截图。
