# 六关51新板首轮与中断恢复

用户要求继续扩大逐板覆盖。本轮保持默认端点策略（setup.policy.continuous_collision=false），main21/phase18、圆心关闭，新增map51两组，从slot1连续进入6002，不假定直接通灵兽落6002安全。源快照firstpass-v46-sources、输出native-firstpass-v46，均在ignored rope-recovery-v37。

首回合seed41010：6001完整穿越，进入6002后死亡，累计5114.03，未进入6003。最后保留EnemyBladeGold引用只是线索，受伤后几何/原图仍需独立核对。

第二回合seed41011计划60011/60021/60031。session84579最终exit143（外部SIGTERM，来源未知），最后保存评估40.250s、60021、damage1200/health3887.57，没有report.json和正常restored，不能按完成/无伤/死亡正式验收。中断后客户端仍推进，手动暂停时已死亡；已关闭visionEval并恢复菜单/键盘。随后通过同名InstanceSession/LocalClient和原prepare重置1101，session11188退出0，manual-restored.json确认health5000、暂停、menu/keyboard true、eval false。

interrupted.json逐项记录已完成/未完成回合及最后保存边界，不补造尾部日志。未把partial目录写成actor通过，不运行第二个控制者。运行源码/用户任务配置未在测试中更改。

当前全部设备/GPU测试进程结束。后续先重跑第二组，再按54批清单补未进入的板；继续研究53041落下一级窄地面时视觉支撑与实际物理阶段不一致，以及低置信坡面相机位移丢失。当前仍远未稳定无伤。


## v47补跑完成

随后按同seed41011、相同60011/60021/60031及main21/phase18补跑，session62439正常退出0，三板穿越、累计4882.5伤。30份source与firstpass-v47-sources逐项相符，正常恢复1101/5000/菜单/键盘/关闭评估。原v46中断目录不回填、不改成通过，v47是独立完整证据。

原血降审计16个唯一事件，未知差额600，保留未见证事件。原报告按键延迟尖峰后来证实受漏键后count错配影响，修正证据及测量口径见[回执时间区间](2026-11-16-arena-key-receipt-intervals.md)，不覆盖原报告。补跑没有达成无伤。
