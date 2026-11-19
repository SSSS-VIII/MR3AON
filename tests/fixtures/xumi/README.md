# 须弥幻境实机样本

2026-11-20在main通过InstanceSession取得，原始画面位于 `deps/bin/debug/xumi-probe/`。均为真实游戏画面，非合成样本。

- `assembly.png`：集会所卡片，原生OCR为「须称幻境」。
- `lobby.png`：活动首页及左右试炼入口。
- `fangcun.png` / `daqian.png`：两种试炼选择页；后者原生OCR为「大千試炼」。
- `tasks_fangcun_pending.png`：初始行序，方寸次数已领但积分仍未达标。
- `tasks_reordered_claimable.png`：方寸积分已达标可领取，任务行发生重排。
- `tasks_only_daqian_pending.png`：方寸两项均已领，仅应选择大千。
- `tasks_all_claimed.png`：四项真实已领取，必须完成退出，不能再选试炼。
- `first_settlement.png`：第一场完成，必须继续试炼，不能视为整局结束。
- `final_settlement.png`：第二场完成，返回须弥幻境。

回放只运行原生识别；业务/设备动作以实机日志为依据，不把图像回放当作完整实机验收。
