# 2026-10-07：TUI 退出、跑图连点与调试工具

## 保留落地

- **TUI**：队列真正跑完 / PiCli 先断开 / 比例拦截等路径调用 `request_tui_exit`，让 Textual 先恢复终端再杀 PiCli，避免 alternate screen 弄坏 shell。
- **跑图点击**：`interruptible_double_click`（中间不 sleep，整段一次 +60ms 修正）+ `bind_parkour_clicks`；各 `my_3v3_kn_*` 改用绑定；录制脚本 `d` 键输出 `doubleclick(...)`。
- **3v3 跑图测试**：`3v3跑图测试entry` 在完成页 OCR 地图名后开测（全图）；`./tools/run-3v3-yan-test` 与任务名对齐；旧「炎之窟跑图测试」名兼容指向同一入口。
- **工具**：`tools/adb-screencap`（设备写文件再 pull，避免 exec-out 混 stderr）；`LoopDeadlineExpired` 超时截图目录最多保留 50 张。

## 试过又撤掉

炎之窟「战斗开始」OCR + 白点双参考点同步（墙钟 deadline、白点可打断）实机两次 OCR→白点间距都稳在 ~2.2s，且截屏采样约 550ms/帧，双参考相对固定延时几乎无额外收益；已整段回退，正式线仍只等高频下滑白点开点。
