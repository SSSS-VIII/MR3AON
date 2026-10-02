# 镜界百器日更登记 + Waydroid/ADB 启动诊断与启动 ROI

## 现象

- `./run` 偶发 ADB 拉不起来：`waydroid adb connect` 看似成功，host `adb devices` 却是 offline / 空列表；失败信息过少不好排。
- 为解冻/对齐分辨率一度多次 `show-full-ui` 并抢 niri 焦点，窗口乱跳；又试过 `immersive.full=*`，系统导航栏被藏，上滑不出返回。
- 启动流程：账密登录密码提示 OCR ROI 偏窄；设置页「屏蔽所有组队邀请」ROI 偏矮，容易卡在「设置页面上滑」。
- 镜界百器清体力 / 每日任务做完后只有当次 `DisableNode`，跨过 05:00 前会反复进队。

## 改动

- `adb_device.list_adb_states`：等待设备时打出全部 serial/state；`waydroid adb connect` 带 `--details-to-stdout`。
- `waydroid_host`：去掉 niri 聚焦；保留单次收尾 `show-full-ui`；**不**再写 `policy_control` immersive（已在设备上清掉）。
- `启动游戏.json`：「账号重新登录密码页面」ROI 水平扩大；「屏蔽所有组队邀请」ROI 高度 `67 → 201`。
- `镜界百器.json`：清体力见「不会获得奖励」、每日任务领完后，分别 `SetManagedTaskPersistentState`（`node`=`清理镜界百器体力` / `镜界百器每日任务`，`next_daily_reset`）；当次仍先 `DisableNode` 以便同一次跑另一支。清体力默认难度仍是炼狱（选项可改）。

## 验证

- `tests/test_pipeline_guards.py`：两处镜界百器登记节点已纳入每日完成断言。
- 待实机：清体力 / 每日任务完成后应禁到次日 05:00；导航栏可上滑；设置页能认出「屏蔽所有组队邀请」。
