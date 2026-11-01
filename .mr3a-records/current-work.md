# 当前工作交接

更新时间：2026-11-01。以工作记录、Git 提交历史和当前代码共同判断进展；已完成项按功能提交，未完成鬼族内容保留在工作区。

## 当前任务：多实例运行隔离

小鲤游戏入口现默认经 `run xiaoli --no-window` 后台启动，设备就绪和 Agent 恢复不再额外打开桌面窗口；普通启动仍显示。相关 54 项测试及现有 Android 热启动无新增窗口、1280×720 截图检查通过；未为验证关闭在用窗口或冷重启设备。见 [小鲤后台启动](archived/2026-11-01-xiaoli-background-start.md)。

命名设备层已在 `c52f41c` 独立提交；现已接入 `./run [名字]`，省略为复用现有账号的 main。新名空白凭据，同名完整复用；检查、恢复、ADB、配置/缓存/奖励、日志及退出按名字隔离，不再复制程序。当前 main 与新建 xiaoli 已就绪，small 经关闭/恢复验证后保持关闭；small 保持空任务；xiaoli 已配置唯一启动游戏任务（OPPO、上次登录），魅族应用及框架已按用户要求卸载。新增 `./run [名字] --stop` 关闭窗口及对应 Waydroid 后台，先退出同名脚本，保留数据；冷启动等待 DHCP。见 [关闭入口与 xiaoli](archived/2026-11-01-named-instance-shutdown.md)、[命名入口落地](archived/2026-11-01-named-run-isolation.md)、[设备会话层](archived/2026-11-01-named-device-session.md)；用法在 `test-environment.md`，后续 dsh 边界在 `docs/develop/命名实例.md`。小鲤独立游戏插件经 `~/xiaoli/run` 调用原启动任务，完成后交还设备，不再常驻占用租约；现已恢复 OPPO 配置并保留原账号数据，见 [恢复 OPPO](archived/2026-11-01-xiaoli-return-oppo.md)；此前魅族试用见 [魅族安装与渠道切换](archived/2026-11-01-xiaoli-meizu-ninja.md)，OPPO 启动验证见 [启动任务交接](archived/2026-11-01-xiaoli-startup-task-handoff.md)。公共设备 ADB 接口见 [接入记录](archived/2026-11-01-xiaoli-device-adb-api.md)；大小号协同业务尚未实现，鬼族继续暂缓。

脚本接入提交为 `ef15765`。截图/录制工具也已按名接入同一设备对象与控制租约，见 [调试工具归档](archived/2026-11-01-instance-debug-tools.md)。MaaPiCli 独立提交为 `7fa3bf2c`（目录参数/临时任务）和 `f42934de`（控制器初始化失败返回错误）。

只跑「启动游戏」的退出排查发现：子进程立即析构及无条件 SIGINT/os._exit 会打断 TUI 和日志队列。已调整为客户端等待 Agent 收尾、q 请求 Runner 正常停止、native 关闭限时；四种实机无点击退出回归通过，见 [启动任务收尾](archived/2026-11-01-startup-only-exit-cleanup.md)。新全量普通回归为 128 passed、5 skipped、5 failed、79 subtests passed，既有失败不变。

奖励列表多余 S/SS 已定位为无实际目录的 `S_SS` 残留登记；列表及迁移增加有效性检查，当前登记已清理，正确的 `S_SS+` 和原图保留。主脚本未中断，运行中的旧 TUI 下次重启加载修复；见 [奖励幽灵分类](archived/2026-11-01-reward-phantom-category.md)。

## 已按功能提交

奖励迁移已按用户要求彻底退场：删除启动迁移入口、迁移实现和旧兼容测试；清理旧源 15 张过期截图及完成标记，当前正常奖励 10 张图片路径/哈希不变，20 项相关测试通过。后续只使用实例自己的奖励目录，不再保留迁移备份机制，见 [迁移退场](archived/2026-11-02-retire-reward-migration.md)；此前问题定位见 [历史奖励迁移](archived/2026-11-02-reward-history-migration.md)。

每周逆袭阶段1列表停判已根据实际截图修正：改读奖励行的 S 剩余次数为 0，不再依赖「刷新」或准备页「次数上限」，阶段2/3显式关闭此判断。真实截图原生 OCR 回放通过；相关回归 30 passed、82 subtests passed、2 项既有失败。当前 main 未重启，在线阶段切换待验证，见 [列表 S 次数修复](archived/2026-11-02-weekly-bounty-list-s-count.md)。

小鲤受限 game_control 新增显式 `takeover`：停止持有 xiaoli 控制锁的脚本、保留 Android，再截图操作。内核锁/pidfd 核验，拒绝停止还控制其它实例的进程；真实占锁脚本已停止，main 原脚本仍运行。见 [受限工具接管](archived/2026-11-01-xiaoli-control-takeover.md)。本轮普通全量回归 137 passed、5 skipped、5 failed、80 subtests passed，既有失败不变。

小鲤启动游戏新增「启动时屏蔽组队邀请=否」，实际配置与模板均已写入，下次启动不打开设置页勾选屏蔽，保留游戏原设置；其它环境默认仍屏蔽。静态保护和真实 Resource 覆盖验证通过，未中断正在操作设备的进程，见 [启动组队邀请选项](archived/2026-11-01-xiaoli-startup-invites.md)。

| 工作 | 提交 | 记录与边界 |
| --- | --- | --- |
| 每周逆袭禁用时间：阶段1/2周日重置，阶段3按月 | `cf7cecb`（原有提交，未重写） | [阶段持久化](archived/2026-10-22-weekly-reverse-stage-persist.md) |
| Wait 正常路径睡醒经 StopTask 推进队列 | `e6fa063` | [Wait 修复](archived/2026-10-28-wait-post-task-abort.md)；对应单测通过，异常兜底与长连断开仍有后续事项 |
| 每周逆袭阶段1列表页优先停判 | `20336e3` | [阶段持久化](archived/2026-10-22-weekly-reverse-stage-persist.md)；保护测试通过，待实机 |
| 家族战宝箱点击 OCR 命中框 | `02be319` | [奖励截图](archived/2026-10-08-reward-screenshots-tui.md)；保护测试通过，待实机 |

## 留在工作区：讨伐鬼族（未提交）

- 流水线：`assets/resource/pipeline/周末活动.json`、新增 `讨伐鬼族.json`。
- 模板：`assets/resource/image/讨伐鬼族.png`、`讨伐鬼族主页面.png`。
- 任务文案：`assets/resource/tasks/常驻任务.json`。
- 草稿记录：`.mr3a-records/archived/2026-10-31-weekend-gui-zu-entry.md`，随未完成功能保留在工作区。
- 状态：集会所 next 仍漏挂点击节点，内流程为返回占位；待继续开发，不算已支持该活动，也不为清空工作区而提交。

## 收口前待办

MFA release 兼容边界已核对：现有本地封装与标准 Adb 控制器没有底层冲突，但 MFA 的实例身份/业务目录/设备绑定、Waydroid 恢复后端及生命周期仍需适配，不能直接宣称发布包多实例可用。方向与验收条件见 [MFA 边界核对](archived/2026-11-02-mfa-multi-instance-boundary.md) 及 `docs/develop/命名实例.md`。

1. Wait 的 `override_pipeline` 异常分支仍回退 `dispatch_next(context.tasker)`，与记录所述「不在 Wait 回调直接 post」不完全一致。结合提交时已带 Stop 节点的实现核实异常策略；控制器长期断连另行验证，不能宣称已解决。
2. `周末活动检查集会所主页.next` 没有 `[JumpBack]周末活动点击讨伐鬼族`。补接后验证入口和退回路径，再继续内流程；当前不算已支持该活动。
3. 处理以下 5 项测试失败。不能为通过断言而撤销历史上有原因的兼容逻辑，也不能未经核实恢复旧业务路径。
4. 后续继续按功能核对 diff 和验证结果；已完成项独立提交，鬼族等未完成项继续留在工作区。

## 2026-11-01 验证基线

`MR3A_LIVE_INSTANCES=main,small PYTHONPATH=agent .venv/bin/python -m pytest tests agent/tests -q --tb=short`：**110 passed、5 failed、79 subtests passed**，包括真实双实例只读截图冒烟和 3 项调试工具路由验证。未指定实机名字时该冒烟默认跳过。

| 失败测试 | 当前证据与处理方向 |
| --- | --- |
| `test_normal_and_deferred_tasks_keep_their_own_override` | 实际覆盖含 `enable` / `enabled` 双字段，断言只含 `enabled`；对照 10-11 兼容修复更新断言并保留配置隔离检查 |
| `test_node_override_applies_to_every_duplicate_without_mixing_base_config` | 同上；保留同入口多实例隔离与持久化禁用验证 |
| `test_startup_override_comes_from_startup_task_template` | 同上；保留启动模板来源验证 |
| `test_weekly_bounty_refresh_mode_button_default` | 引用了已不存在的独立「误入悬赏令商店点返回」节点；当前共享返回节点已联合识别店名和返回按钮，需据实际可达链路核对断言 |
| `test_bounty_shop_alternates_swipe_direction` | 真实入口只进右滑计数链，左滑切换节点虽在但不在该路径；与 09-27 交替滑动记录不一致，需确认预期再修代码或记录，暂不能只改断言 |

资源 JSON 和鬼族图片的原检查结果保留。本轮已做两台 Android 并行只读截图、运行文件归属及次实例按名重启验证；未执行游戏点击或改主账号任务/密码，长睡、跨日与协同业务仍未验证。
