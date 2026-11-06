# 当前工作交接

2026-11-06：外部任务调用现支持 `--task-options` 本次覆盖与 `--once` 单次执行。完成/已完成跳过返回0，失败1，参数错误2，周期延后3，一小时让出4，SIGINT/q中断130，SIGTERM143；退出释放控制权并保留 Android。small 无点击真实进程9项通过，普通回归205 passed、14 skipped、5项既有失败、85 subtests passed；未实跑逆袭/备战业务。small 保留运行，main 未接管，xiaoli 保持停止。详见 [单次退出](archived/2026-11-06-single-run-exit.md) 和 `test-environment.md`。

2026-11-06：单次执行验证发现后台命名容器可在会话存活时冻结，start 现按名字调用 Unfreeze 后再检查设备，small 实测恢复，27项相关回归通过，见 [冻结实例唤醒](archived/2026-11-06-resume-frozen-named-instance.md)。

2026-11-06：run 已增加本次任务选项 JSON 覆盖，原生 MaaPiCli 接收内存任务配置并复用现有选项转换，保存计划保留。33项相关回归通过，见 [本次任务选项](archived/2026-11-06-invocation-task-options.md)。单次执行模式已接入，后续收口见本页最新记录。

2026-11-06：鬼族活动草稿已按用户要求撤回。深渊挑战已接入家族战同款挂起调度，开启等待时周五20:00前交回队列，到点恢复并沿用选卡配置，保留既有21:00截止；跳过/结束登记到下一次每日重置。代码未发现自动领取宝箱或个人积分奖励分支。10项相关回归与原生资源加载通过，未实机验证，见 [深渊周五调度](archived/2026-11-06-abyss-friday-deferred.md)。

2026-11-04：v1.6.2已在 `integrate/upstream-v162` 按功能实施：7项bug修复、一次性阶段进度/暂停与计划校验、独立时序能力、新号14段及10个动作接入，框架保留5.14.2/定制MaaPiCli。最终离线回归172 passed、5 skipped、5项既有失败、85 subtests passed，原生资源及CLI加载通过。用户明确本轮不实跑，新号全流程待后续验收；运行实例未动，详见 [分批实施收口](archived/2026-11-04-v162-onboarding-integration.md)、[起号用法](../docs/develop/新号起号.md)。前期判断保留在 [v1.6.2评估](archived/2026-11-04-upstream-v162-integration-assessment.md)。

2026-11-04：小鲤清晨首轮启动因设备截图不返回触发 600 秒外层超时，第二轮启动检查也超时；她自行 stop/start 后恢复。底层阻塞原因尚未确定，未修改 MR3A 运行逻辑；模型侧故障编号与转述要求在 xiaoli 仓库清理，见 [清晨截图阻塞](archived/2026-11-04-xiaoli-startup-screencap-hang.md)。

2026-11-03：小鲤随开机启动的进程未继承后建桌面的显示变量，导致无窗口游戏启动查找错误 socket。入口现核验调用者连接并回退用户管理器当前环境，41 项相关回归通过；实机冷启动返回 ready 及 1280×720 截图，已交还控制权。见 [后台显示连接修复](archived/2026-11-03-background-display-environment.md)。

更新时间：2026-11-01。以工作记录、Git 提交历史和当前代码共同判断进展；已完成项按功能提交，鬼族未完成草稿已于2026-11-06撤回。

## 当前任务：多实例运行隔离

2026-11-02 小鲤启动后锁不释放已修复：改从真实持 fd 进程核验继承锁，兼容父进程退出及挂载设备号差异，仍保留多实例保护。43 项相关测试通过，实际回收残留截图进程并完成同名启停，返回原账号主页；小鲤工具将接管与维护诊断封装在 start/stop 内。见 [继承锁回收](archived/2026-11-02-orphan-control-lock.md)。

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

## 讨伐鬼族草稿已撤回

2026-11-06用户决定等下次活动，入口草稿、占位流程及两张模板已撤回，详情见 [鬼族撤回记录](archived/2026-11-06-gui-zu-draft-withdrawn.md)。

## 收口前待办

悬赏战后卡住已定位并修正等待：每日悬赏 5 次日志和 S 悬赏 24 帧实测表明，确认点击后约一秒仍显示结算，过早重新截图，随后转页导致下一次确认 OCR 等到超时。六条确认点击统一等待 1500ms，截图流程不变、无无条件放行出口；原生时序回归通过。main 尚未重启加载，新配置在线全流程待验证，见 [结算时序排查与修复](archived/2026-11-02-bounty-settlement-timing-investigation.md)。

用户已明确后续保留定制 MaaPiCli，参考 MFA 设计自己的模拟器兼容层，暂不全面兼容 MFA；当前仍优先业务修复。统一启动路径/参数、设备绑定与目录隔离，Waydroid 为后端之一，见 [MFA 边界核对及方向修正](archived/2026-11-02-mfa-multi-instance-boundary.md) 及 `docs/develop/命名实例.md`。

1. Wait 的 `override_pipeline` 异常分支仍回退 `dispatch_next(context.tasker)`，与记录所述「不在 Wait 回调直接 post」不完全一致。结合提交时已带 Stop 节点的实现核实异常策略；控制器长期断连另行验证，不能宣称已解决。
2. 处理以下 5 项测试失败。不能为通过断言而撤销历史上有原因的兼容逻辑，也不能未经核实恢复旧业务路径。
3. 后续继续按功能核对 diff 和验证结果，已完成项独立提交。

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
