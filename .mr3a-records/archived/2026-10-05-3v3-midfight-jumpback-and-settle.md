# 3v3 战内失败 JumpBack 清结算 + 炎图 p2 / 单独跑

## 现象

- 进了 p1、进了商店之后经常进不了 p2：等金鱼币（`33金鱼币.png`，阈值 0.8）失败，原先走 `3v3_boss战斗循环超时` → `Default_on_error` → 重启，结算「继续/确定」清不掉。
- p1 跑完没进商店时同样：观战进度页有「返回」，等「卡片商店」30s 超时后也直接重启。
- 炎图 p2 曾是挂机 sleep；超时截图未存（`LoopDeadlineExpired` 是识别成功，不是 Task timeout，`save_on_error` 不触发）。
- 需要测试环境单独跑完整 3v3，而不是改日常任务列表。

## 原因

- 原版 p2 叶子无 `next`，整场挂在 `3v3确定进入了作战页面` 的 `[JumpBack]3v3进入准备页面` 下；战内失败应空 next / 收束后 **JumpBack 回作战页** 再清结算，而不是 `Default_on_error`。
- 战内超时用的是 `LoopDeadlineExpired` 命中，不是节点 reco_timeout，所以默认不会存图。

## 改动

- `3v3.json`：boss `LoopDeadlineArm` `120s → 240s`；`3v3_boss战斗循环超时` `next: []`。
- 战内等待节点（下滑后购卡 / 购卡链 / 发现 boss / kn_*_p1）`on_error` → `3v3战内失败收束`（DirectHit + 空 next）→ JumpBack 回作战页。
- 作战页 next 增加 `[JumpBack]3v3观战返回等待消失`：OCR「返回」→ `post_delay` 5s 再认，直到消失 → 点屏幕中央 `(640,360)` → 再处理结算/继续。
- `LoopDeadlineExpired` 首次到期把当前帧存到 `debug/loop_deadline_expired/`（相对 cwd）。
- `tools/run-3v3`：同 `run-3v3-yan-test`，在 `deps/.run-test` 只跑「3v3（仅支持困难图）」→ `3v3entry`。
- `my_3v3_kn_yan_p2`：补齐点击序列用的 import（`ClickDelayState` / `interruptible_click` / `click_delay_calibrate`）。

## 验证

- `./tools/run-3v3`：能进决斗场→匹配→炎之窟；p1 后若进观战，应 JumpBack 等「返回」消失再点中间并清继续，而不是立刻重启。
- 金鱼币命中进 p2 后仍靠作战页 JumpBack 清结算（与原版一致）。
- 超时截图目录：`debug/loop_deadline_expired/`（run-test 下为 `deps/.run-test/debug/loop_deadline_expired/`）。
