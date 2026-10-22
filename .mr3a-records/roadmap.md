# Roadmap

已完成错误恢复重构：默认错误与普通 `back` 分流；全局恢复回主页后每个 task 最多重试一次；重启使用启动 task 记录的实际包名；恢复耗尽后停止整个 Tasker。

每日商店从入口起算 10 分钟。神秘商店和悬赏商店每圈都先看这个截止时间，到点进入 `Default_on_error`，由 Agent 排回退并重跑该任务。神秘商店仍购买全部忍币商品。勾玉碎片待选项只在「忍币购买神秘商店」勾选 cases 里维护；Agent 只读 attach 已选项。可用手动 Action 从 BWiki 刷新 cases。改名单需发版。默认不选。勾选后只认第 8 商品位卡面全名，确认付款图标再点购买。

通灵「点击通灵兽」已改侧栏文字绿幕模板匹配（`通灵兽侧栏文字.png`），实机 score≈1 点进巡逻页；早先 OCR 兜底不足以应对白底白字漏检。战令红点模板已开 green_mask、补 红点1、放宽 ROI。好友饭团主页误判仍未处理。神秘商店里未挂接的「配置碎片」死节点已删。

已修复藏宝图等待进入 fight 的节点：用 `inverse` 等待 `进入战斗中.png` 消失，存在时按 `rate_limit: 2000` 重试，消失后才进入 `fight`；默认 timeout 显式设为 30 秒。相同的“清自己藏宝图”分支同步修复。

task/重复节点的通用无进展 watchdog 与 `进入战斗中.png` 页面上下文联合识别仍未采用；当前已知误匹配会在后续 `fight` 全 miss 后由 timeout 接入全局恢复。

已为启动流程接入现有 `LoopDeadline`总时限：正常启动 6 分钟后关闭游戏，再用已记录的包名重新打开，然后回到启动流程。业务任务的恢复启动 2 分钟后再次 `RestartGame`。该时限使用 Agent 单调时钟，不会被节点持续识别成功或 JumpBack 重置。

后续继续使用临时 MaaPiCli 副本做真实设备验证，正式入口缓存不动。Agent 运行时 TUI（Textual，竖屏半窗 / btop 风）已接入：TTY 下默认开启，`MR3A_TUI=0` 关闭；列表含排队与延后未提交项；waiting 显示最近到期任务名；`q` 先 SIGINT 同 TTY 的 MaaPiCli 再退出，应直接回 shell。

已实现 Agent 接管 MaaPiCli 任务队列的延后任务调度试点：MaaPiCli 只提交一个
bootstrap，Agent 将每个业务任务作为独立顶层 task 逐项提交。业务流水线即将执行
`StopTask` 时由 context sink 先提交下一项；自然返回则由 wrapper 尾部 finalize 兜底。
真实 MR3A interface 已验证 `启动游戏 -> 领取饭团 -> 小屋修炼 -> AgentSchedulerWait`
连续执行；小屋 OCR 到 `随机访问20小时02分` 后登记到期时间并退出，Agent 保持等待。
已扩展到通灵巡逻、忍村试炼、藏宝图和 3v3：通灵巡逻按实际倒计时或 2 小时估值挂起；忍村试炼每 4 小时挂起并记录历史最大挑战次数；藏宝图连续运行 1 小时后在安全节点一次性让出；3v3 因时间未开放退出时，无视 OCR 内容按每日 13:00/20:00 固定时点挂起。

2026-08-29 长时运行确认 Agent 主队列整体能够持续工作，但发现两个配置/恢复问题：活动配置遗漏 3v3；藏宝图刷新冷却节点的一小时让出检查缺少未命中兜底，造成 30/60 秒超时交替重启。3v3 已恢复到本机活动配置；藏宝图已补 `藏宝图None` 末端兜底。

全局错误恢复已完全交给 Agent 重排，不再使用嵌套 `Context.run_task()`：主页异常把当前任务放回队首；非主页异常先停止游戏，再依次排入启动任务和原业务任务。当前顶层流水线随后执行自己的 `StopTask`，由 sink 提交下一项，因此不会继承旧 JumpBack 栈，也不会被子任务停止状态连带结束。

待下次实机长时运行验证：藏宝图跨刷新冷却持续刷取、重启恢复不再继承错误路径，以及 3v3 到 13:00/20:00 的固定时点重排。

Agent 启动终端的大块乱码已确认是截图头被 Waydroid `amdgpu.ids` 警告污染后，MaaFramework 将 PNG 二进制作为 Error 输出。不修改框架，本机运行配置关闭框架 stdout，日志仍写文件；Agent 另外禁用 MaaPiCli 子进程中的 ANSI 颜色，并用 `realpath` 修复 build 软链接下的项目根识别。

3v3 跑酷点击时序改用绝对时间轴：原始 delay 先增加当前 `+60ms` 环境修正，再动态扣除每次 ADB `controller.wait()` 的真实耗时；超时欠账由后续间隔偿还。当前一次性首段校准为 `1000ms`，每次点击均输出坐标与时序明细。

2026-10-02：炎之窟 p1 用 `record-3v3-parkour` 人手间隔原样粘贴后，相对录制基线每步固定慢约 `+60ms`（47 步累计约 +2.8s）；`debt=0`，说明绝对时间轴按「delay+60」执行正确，多出来的是修正与 raw 录制叠用。要点：粘贴进 `my_3v3_kn_*` 前每个 delay 减 60（或用录制脚本导出的已扣减值）；日志 `gap=` 仍是原始间隔。`my_3v3_kn_yan_p1` 已按 `20261002-180115` 扣 60 写回；recorder 输出会注释并自动减 60。明日实机：主路径困难图选关含炎之窟、p1 时序、p2 仍为可中止挂机占位待录制。`__init__.py` 补齐其余地图 kn action 的 import，避免只注册了暗之狱 p1。

已实现 Agent 持久化任务启用覆盖框架：PiCli 候选任务在 Agent 加载阶段按 `deps/bin/config/agent_task_state.json` 标记启用状态，状态文件在启动加载时自动初始化。禁用候选仍保留在队列中；有效期结束或每日 05:00 后，在下一个 Agent 调度安全点重载并恢复执行，不用后台定时器中断业务任务。顶层任务及子节点均可覆盖；同入口的多个不同配置实例分别保留自己的 PiCli 基础 override，节点状态统一覆盖所有实例。已提供通用状态写入 action。
已登记完成的当前任务实例会作为下一周期休眠候选继续保留在 Agent 内部，不会立即提交；这保证长时间运行跨过 05:00 后，已经在上一周期执行过的任务仍能从原 PiCli 候选及其 override 恢复。

已按本机当前运行计划把明确成功出口接入完成登记：领取饭团和另外 8 个顶层日常任务，以及“领取奖励”的 5 个子任务已登记；其中每周兑换码登记到下周五 05:00，其余登记到下一个 05:00。启动游戏、小屋修炼、好友忍币、领取邮件、忍阶任务、持续藏宝图及所有挂起/未开放/让出出口不登记。

已为官服已有账号重新登录页面补充自动密码登录：启动流程可识别并点击“账密登录”，兼容可选的“同意并继续”弹窗，进入密码页后清空输入框、从 PI 输入选项读取密码、关闭软键盘并点击登录。实机日志确认页面识别和输入框操作链路正常；密码必须配置在 `inputs.登录密码`，普通 `value` 字段不会参与 input 类型占位符替换。本机密码仅保存在忽略提交的 `deps/bin/config/maa_pi_config.json`。

已修复小屋领取修炼成果后的第二次确认：周四 17:21 实机日志确认第一个碎片“确定”点击成功，但“继续修炼”弹窗右侧按钮超出原 OCR 右边界，连续识别失败 31 次后超时。仅将“确定继续修炼”的 ROI 右边界由 `x=954` 扩至 `x=1116`，第一个确认节点保持不变。

周末活动补两层时间兜底：仍仅周六/日进入；未到 09:00 时按 `daily_times` 挂起到九点（同 3v3）；任务内把 `Default_on_error` 末项从立刻 `重启游戏` 改为挂起一小时后 `StopTask`，避免清晨入口未开时饿死其它日常。成功完成与非周末跳过均登记到下一 05:00，过夜跨日可再进，平日不会反复进队只为检查星期。

家族战同样：仅周六/日；未到 20:00 挂起到八点；完成/未报名/非周末/已过 21:20 均登记禁用到下一 05:00。任务选项与文案不动。

小屋领取修炼成果并确认继续后，改为回到 `进入了忍者小屋页面` 再认倒计时挂起，避免直接回主页把任务消费掉、同一会话不再检查。

通灵巡逻不足文案改为同时认「兵粮丸不足」；命中后登记禁用到下一 05:00，避免误重启死循环。悬赏商店每轮滑动改为左右交替，避免卡在最右侧看不到左侧商品。

镜界百器清体力与每日任务已分别挂节点级日更禁用（`next_daily_reset`）；当次仍 DisableNode 以便同跑另一支。清体力默认炼狱。Waydroid 启动侧补了 ADB devices 诊断与 connect 详情，去掉多次 show-full-ui/niri 抢焦点，且不再用 immersive（会藏返回栏）。启动流程：密码页 ROI 水平加宽；设置「屏蔽所有组队邀请」ROI 高度扩到约三倍。

2026-10-05：3v3 战内失败（金鱼币/商店等）改为 JumpBack 回作战页清结算，不再默认重启；boss 循环 240s；观战「返回」等消失后点中央；`LoopDeadline` 到期落图；`./tools/run-3v3` 单独跑完整 3v3。详见 `archived/2026-10-05-3v3-midfight-jumpback-and-settle.md`。

2026-10-05：已合并上游 MR3A（`maafw` 5.14.2 等）；流水线冲突以本地为底、重叠修法跟上游。定制 `MaaPiCli`（`mr3a-managed-queue`）已 merge `v5.14.2` 重编对齐协议 8。本机已清空 `agent_task_state.json`。详见 `archived/2026-10-05-upstream-merge-and-maapicli-5142.md`。

2026-10-06：3v3「满了也刷」挂到任务；每场回决斗场先 Yield 再 StopTask；超时 SetManaged 挂到次日 11:00。详见 `archived/2026-10-06-3v3-full-and-keep-farming.md`。

2026-10-07：S/SS+ 完成回主页后与每日悬赏相同，`SetManagedTaskPersistentState` 禁用到下一 05:00。详见 `archived/2026-10-07-sss-daily-persistent-disable.md`。

2026-10-07：队列真正跑完或 PiCli 先断开时，主动 `request_tui_exit` 让 Textual 先恢复终端再杀 PiCli，避免 alternate screen 残留弄坏 shell。同日另落地跑图 `doubleclick`/录制 `d`、全图完成页认图测试、`adb-screencap` 与 LoopDeadline 超时截图上限；炎之窟 OCR「战斗开始」双参考点试过后已撤回。详见 `archived/2026-10-07-3v3-tui-doubleclick-and-tools.md`。

2026-10-08：结算确认前增加同 OCR 的截图节点 `SaveRewardScreenshot`（仅存图，dir 入参），再 DirectHit 点击原确定节点；图在 `debug/reward_shots/<dir>/`，TUI 当前任务面板下方可浏览（d / ← / →）；日常 05:00 周期外清理。已挂每日悬赏 / S_SS+ / 家族战。神秘商店在进店与每次刷新回「自动刷新」八格列表时截整页（dir=神秘商店）。奖励区仅 Kitty TGP 单图；左侧 OptionList 自选目录（↑↓），←/→ 翻图；非 Kitty 只提示不支持。详见 `archived/2026-10-08-reward-screenshots-tui.md`。

2026-10-09：每日悬赏 / S_SS+ 结算 JumpBack 连点会狂截；`burst_replace`（10s）同场只覆盖留最后一张 `b00N.png`，跨场新开编号，任务重开跳过已有文件。家族战未开。详见同上 archived。

2026-10-10：家族战截图只挂 `族战宝箱确定` 前（`burst_replace` 3s，确定后 `post_delay` 3s）；结算/参战奖励直接领取；撤掉误挂的战报确定截图；主页 next 增加关闭「个人信息」误点。详见同上 archived。

2026-10-10：启动游戏 `勾选屏蔽` OCR roi 对齐 `屏蔽所有组队邀请`，避免认到文案却点不了勾选。详见 `archived/2026-10-10-startup-block-invite-roi.md`。

2026-10-08：主页已开着再跑脚本时，`启动应用` 无条件 StartApp 会再给前台 Unity 发 MAIN，间歇性 pause 超时卡死。改为 `StartAppIfNeeded`：`pidof` 已有进程则跳过；服务器包名 override 写入 `custom_action_param`。TUI 退出与 Abort 时强制清 alternate screen / Kitty 图，避免弄坏 shell。详见 `archived/2026-10-08-startapp-skip-if-running.md`。

2026-10-22：每周逆袭悬赏按藏宝图同款一小时安全点让出（主页/仍在主页/战后回页；不挂刷新热路径）。流水线后续上游可能改，合并时对照 archived。详见 `archived/2026-10-22-weekly-bounty-hourly-yield.md`。同日补结算截图（同悬赏令）；每日悬赏 / S_SS+ / 每周逆袭 / 每日逆袭（三支）`burst_gap` 统一 30s。

2026-10-22：每周逆袭「逆袭A和逆袭S」改为三段停判：S奖励上限 → A概率掉落 → S概率掉落；仅A/仅S为子阶段。详见 `archived/2026-10-22-weekly-reverse-three-stage-stop.md`。

2026-10-22：每周逆袭三段按镜界百器同款独立 `SetManagedTaskPersistentState` 至下周日 05:00；每日逆袭整单完成后禁用到次日 05:00（每日悬赏原本已有）。详见 `archived/2026-10-22-weekly-reverse-stage-persist.md`。

同日：每周逆袭顶栏停判改为宽匹配「次数上限」。

同日：每周逆袭阶段停判改到准备开战页（对齐每日逆袭刷出A顶栏）；列表页只切筛选。详见 `archived/2026-10-22-weekly-reverse-stage-persist.md`。
