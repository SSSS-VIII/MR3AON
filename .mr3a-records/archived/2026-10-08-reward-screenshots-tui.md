# 结算 / 神秘商店截图与 TUI 浏览

## 现象 / 需求

悬赏类结算确认前要留图备查；神秘商店每次「自动刷新」回八格列表时截整页。Agent TUI 里能浏览这些图。

## 改动

- 自定义动作 `SaveRewardScreenshot`：按 `dir` 写入 `debug/reward_shots/<dir>/`，登记并做日常 05:00 周期外清理；目录名允许 `+`（如 `S_SS+`）。每日悬赏 / S_SS+ 结算开 `burst_replace`（间隔默认 10s）：低于间隔覆盖同场 `b00N.png` 只留最后一张，超过则新开场；任务重开跳过已有编号。家族战与神秘商店不传。
- 流水线：每日悬赏 / S_SS+ 在原「结算确定」前插入同 OCR 截图节点，再 DirectHit 点确定；家族战仅在 `族战宝箱确定` 前截图（`burst_replace` 3s），结算/参战奖励仍直接领取，战报确定保持上游；另挂关闭「个人信息」误点。神秘商店相对上游只改 `点击神秘商店.next` 并加一个纯截图节点（→原`神秘商店页面`）。
- TUI：当前任务面板下方奖励区，仅 Kitty TGP 单图；`d` 打开目录 OptionList，←/→ 翻图；非 Kitty 只提示不支持。依赖 `textual-image[textual]`。

## 踩坑

截图若 next 接到无参 `ResetCount`，会清掉 `神秘商店任务` Count；不足结束后 JumpBack 又再进店空转至超时。截图只该存图再回原 next；也不需要第二条刷新截图节点。

## 验证

- `pytest agent/tests/test_reward_shots.py agent/tests/test_ansi_image.py`
- 实机 Kitty 下浏览截图。
