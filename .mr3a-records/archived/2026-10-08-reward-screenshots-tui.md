# 结算 / 神秘商店截图与 TUI 浏览

## 现象 / 需求

悬赏类结算确认前要留图备查；神秘商店每次「自动刷新」回八格列表时截整页。Agent TUI 里能浏览这些图。

## 改动

- 自定义动作 `SaveRewardScreenshot`：按 `dir` 写入 `debug/reward_shots/<dir>/`，登记并做日常 05:00 周期外清理；目录名允许 `+`（如 `S_SS+`）。`burst_replace` 两种场次：无 `burst_entry` 时按 `burst_gap_sec`（默认 10s）同场覆盖；有 `burst_entry` 时按「同入口连续保存」覆盖，主页同 next 命中其它候选则新开。任务重开跳过已有编号。
- 流水线：每日悬赏 / S_SS+ 在原「结算确定」前插入同 OCR 截图节点，再 DirectHit 点确定（`burst_gap` 10s）。家族战：入口=截图同一节点 `族战宝箱确定截图`（OCR「确定」→ `pre_delay` 1s → 截图 → `族战宝箱确定` 点击 `post_delay` 3s）；`burst_entry` 即本节点；结算/参战奖励不截；另挂关闭「个人信息」误点。神秘商店相对上游只改 `点击神秘商店.next` 并加一个纯截图节点（→原`神秘商店页面`）。
- Agent：`runtime_status` 记全局识别成功与当前 next 列表；`TuiStatusSink` 维护，供 `burst_entry` 打断（无专用 sink / 主页白名单）。
- TUI：当前任务面板下方奖励区，仅 Kitty TGP 单图；`d` 打开目录 OptionList，←/→ 翻图；非 Kitty 只提示不支持。依赖 `textual-image[textual]`。

## 踩坑

截图若 next 接到无参 `ResetCount`，会清掉 `神秘商店任务` Count；不足结束后 JumpBack 又再进店空转至超时。截图只该存图再回原 next；也不需要第二条刷新截图节点。
家族战勿把截图拆成独立保存节点：保存的「上一节点」会永远是入口，无法表达连续入口；入口与截图必须同一节点。`burst_gap` 3s 小于「点确定+post_delay 3s」一圈，会误开多场。

## 验证

- `pytest agent/tests/test_reward_shots.py agent/tests/test_ansi_image.py`
- 实机 Kitty 下浏览截图。
