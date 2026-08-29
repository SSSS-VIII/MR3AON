# 长时实机运行诊断与原生恢复收尾

## 本轮完成

- 全局恢复回到主页后，不再用 `override_next` 接回仍携带旧 JumpBack 栈的外层流水线。
- `RetryCurrentTaskAtHome` 改为通过 MaaFramework 原生 `Context.run_task()` 创建空 JumpBack 栈的内层任务，从原业务入口恢复。
- 内层 Context 继承当前 pipeline override，并与外层共享 TaskState 和停止标记，因此 PI 配置、`max_hit`、anchor 等状态不会丢失；完成后先 finalize Agent 调度，再停止外层旧任务。
- 保留同一 task ID 仅允许一次主页恢复的限制。
- 修复藏宝图的一小时让出检查：`藏宝图仍在寻宝助力页面` 在让出信号未命中时进入 `藏宝图None`，使当前支路正常结束并弹出 JumpBack，继续刷新。

## 2026-08-29 长时运行结论

### 3v3 未执行

- 实际提交给 Agent 的活动任务列表没有 `3v3（仅支持困难图）`，因此流水线和固定时间挂起逻辑均未获得执行机会。
- 仓库的日常预设包含 3v3，但预设不会自动合并进已经保存的 `deps/bin/config/maa_pi_config.json`。
- 从 Neovim ShaDa 的删除寄存器恢复出原任务对象；其 `option` 为空。现已重新加入本机活动队列，位于“每日悬赏”之后、“领取奖励”之前。
- `deps/bin/config` 被 Git 忽略，该配置只存在于本机运行环境，不随本提交入库。

### 自己的藏宝图未清空

- 每日藏宝图确实进入过“清自己的藏宝图”分支，并正确应用绝品、珍品、凡品的“海之国”配置。
- 当次页面和连续滑动后的 OCR 只看到神炎国、云之国等藏宝图，没有出现已配置的对应目标，因此该分支按滑动次数上限正常结束。

### 后续数小时反复重启

- 独立藏宝图正确配置为只刷“神品海之国”；没有目标时本应持续刷新等待。
- 刷新冷却显示 `4s` 等文本时会命中 `藏宝图仍在寻宝助力页面`。该节点原本是末端节点，用于结束支路并返回 JumpBack 栈中的 `藏宝图核心节点`。
- 一小时让出改动曾把它的唯一后继设成 `藏宝图检查让出调度信号`。未到一小时时该识别必然 miss，导致节点等满默认 30 秒并进入 `Default_on_error`，而不是回到核心节点。
- 恢复重启后，旧 JumpBack 又可能让主页面直接进入只识别藏宝图内部控件的 `藏宝图核心节点`，再等满 60 秒后重启，于是形成 30 秒与 60 秒超时交替。
- 日志在 13:37 至 17:40 记录了 169 次“重启游戏”；期间只有一次找到目标并尝试加入队伍，没有进入准备或战斗。

## 验证边界

- Agent 错误恢复单元测试覆盖了空栈 wrapper、业务入口、finalize 和 StopTask 结构。
- JSON 配置已通过解析检查。
- 本轮未启动或操作游戏，等待下一次实机长跑确认藏宝图能跨刷新冷却持续运行，以及重启恢复不再继承旧 JumpBack 栈。

## Agent 启动终端乱码

- 最初发现 Agent Loguru 强制输出 ANSI 颜色控制码；已改为 MaaPiCli 子进程模式禁用颜色，并统一 stdout/stderr 的 UTF-8 输出。
- 实际的大块乱码不是字符编码，而是 Waydroid 的 `adb exec-out screencap -p` 在 PNG 前输出 `/vendor/etc/hwdata/amdgpu.ids: No such file or directory`；MaaFramework 因 PNG 头校验失败，将整张截图作为 Error 文本打到终端。
- 不修改 MaaFramework，本机运行配置 `deps/bin/config/maa_option.json` 将 `stdout_level` 设为 `0`；框架日志仍完整保存在 `debug/maafw.log`。该运行配置被 Git 忽略，不随提交入库。
- MaaPiCli build 目录通过软链接使用 MR3A Agent 时，`abspath(__file__)` 会误把 `/home/linn/MaaPiCli/build` 当成项目根，导致 interface、requirements 和 `.venv` 查找错位。已改用 `realpath(__file__)`，确认项目根和虚拟环境分别回到 `/home/linn/MR3A` 与 `/home/linn/MR3A/.venv`。
