# 原生任务与致死来源的只读验收

## 需求与排查

上一轮水果板仅看到切水果目标及HP归零，缺少明确致死来源；damage=0或Enemy类名不能替代触发语义。追加到独立验收层的只读信息，不进入像素策略。

## 改动

vision_eval快照新增原GameTaskManager的当前特别/即时任务类型、目标species、计数和描述；原EnemyManager.KillNinjaEnemy的实例/名称/类型/位置/原_killedNinja标记，以及原StuckByBlock/BeDragToUnderground属性。任务组件只在每回合开始查找一次。读取受pcall保护，失败写interactions_error，保留原血量/时间/状态验收。没有给任务加分、替换回调或改变原游戏行为。

StuckByBlock在正常运行时也为true，现命名stuck_by_block_flag并保留原值；不能把它作为本帧堵墙事件。位置停滞、相邻原块边界和像素证据须共同判断。

## 实机证据

25012原策略复测242个原生快照、0读取错误，水果板x538.3/y-0.75停滞，KillNinjaEnemy空、原dieDownLine，任务仅3/80。实际原生成：绳段结束539.1、下一地面起539.4。原录像与后续像素地形修复相互核对，直接问题为绳下撞地面入口，不能误称收集任务未完成导致死亡。

同seed零按键对照578快照/0错误；角色正常经过水果板，日志最高79/80后进入3004（不排除采样间到80，因此不单凭79判未完成），最终第三板被原EnemyDart2Fire杀死，快照成功记录对应_killedNinja=true。进一步地形规划实跑三板通过，水果计数仅36/80，证明这里80目标是额外任务而非必须通关条件。原EnemyFruitBase接触回调展示切割光效并延迟EnemyKilled，后者调用AddCutFruitNum，禁止仅凭damage0推广到所有对象。

诊断源与原图/原始记录在忽略的fruit-v11-native-trace25012、fruit-v11-native-idle25012、fruit-v11-postmortem.json、fruit-native-callgraph-v11.txt、fruit-task-native-callgraph-v11.txt。新字段不参与模型推理，也不是完整死因枚举；空KillNinjaEnemy不能单独排除所有伤害。
