# 情报模拟战推演策略接入原生流水线

## 需求与原状

用户要求先把当前策略真正接进脚本，把活动放到3v3前，再讨论优化；当前没有实机环境，使用历史截图验收。提前达到100更好，不能为提高第五回合均伤关闭击杀优先。

原生产PlanIntelligenceHand仍只调用角色后缀白名单；离线策略没有金币、棋盘及回执适配，不能因为工具已完成而称运行入口已接入。本次完成实际调用链，不运行任何命名实例，不继续调参。

## 改动

- 共用实现移到`agent/intelligence_strategy`，运行Agent直接导入，旧`tools/intelligence_simulator`保留命名空间转发，源码/牌库/原生核只有一份；工具样例路径仍可用。
- 接入64次单边余池推演、未来限宽8、候选组合6，650ms推演预算；当前手牌仍先枚举合法组合与位置。所有候选使用共同样本，超时时只用完整覆盖全部候选的批次，没有完整批次就退回启发式，拒绝前缀偏差；模拟检查实物张数守恒。不读取实际后续发牌。
- 生产调用显式固定`prioritize_finish=True`，模拟未来也保留同一优先级；可本轮击杀时直接优先本轮终结，未采用关闭优先击杀的试验。未来模拟另保留提前击杀奖励10。
- 原生批量OCR提供完整卡名、金币、剩余刷新次数、对手血量和空格；唯一全名/单字OCR纠错认牌，不用小黑等歧义后缀猜变体。未知卡槽仍算待刷新槽，不误当已买空槽。
- 匹配前WarmIntelligenceStrategy重置局面并预热C++17核；正常倒计时内只算决策，不编译。编译缺失/失败会日志标记并保守回退，不阻塞其它日常。
- 原PlanIntelligenceHand已调用共用策略，仍只配置原生“点牌→点格子”队列。新增原生确认落位扫描，金币支出、目标非空、原商店槽消失相符后才提交棋盘；失败点击不冒充成功。Python不截图、不OCR、不直接发控制器输入。
- 账本在同实例`data/intelligence-battle-state.json`原子保存，包含已确认牌、入场回合、待确认动作；新匹配重置，恢复已有对局不凭空重建未知牌。状态不一致/冷恢复未知局/计算异常时回退受金币和空位限制的旧候选。金币未知不盲买，后期血量未知优先当前伤害。
- 读取实际剩余刷新并受当前流水线阶段上限约束，第二轮不会因刷新点击失败或图像未变而反复刷新；“已刷新”明确当0。恢复时已准备则等对手，不再次购买。回合参数及当前回合识别一起约束两轮，避免跨回合旧节点误操作。
- 日常预设、main现有17项保存任务均移动情报模拟战至3v3紧前，保留其它任务、选项、账号与完成账本。main配置在忽略的deps/bin/config/maa_pi_config.json，仅本地调整，不入Git。

## 历史截图验收

保存的5张对局图：原round.png（第1回合、5金）、xiaojiao.png（第4回合、20金）、新增purchase_before/after.png及four_tigers.png。后3张原样取自旧main录帧和小鲤研究历史图，没有连接实例，也没有修改像素拼接出成功画面。

真实购买前后：live3-frames/10-11-25.png→10-11-28.png，8金降为6金，星闪·小椒从商店槽1消失并出现在棋盘格1。原生识别输出经实际会话确认逻辑成功登记，原有苍牙保留。四虎图识别13金、对手92血、已刷新0；模型四虎即时14攻击与图中角色4/4/2/4及左上14一致。

MaaFramework内存控制器加载正式资源并注册实际PlanIntelligenceHand、ConfirmIntelligenceHand、NodeOverride动作类，跑过第1回合以及第4回合入口→原生选牌点击→确认→刷新/准备。第4回合真实覆盖NodeOverride参数传递；直接Python控制器截图/点击/滑动入口在测试中设为禁止。恒定图片不产生扣币/消失回执时，棋盘仍保持未购买，不能乐观记账；正向确认使用上述真实前后图。

回放修正了窄血量ROI/锚定正则漏读92、零刷新OCR和仅顶行第3槽剩牌的可见性判断。完整卡名、5/20金、血量100/99/92、0/1次刷新与实际购买回执均有断言。仍不把内存点击当成真实游戏点击成功。

## 验证与边界

- 相关91项离线回归通过；覆盖旧白名单回放、日程/结算/每日领奖、组合引擎、推演、预算回退、实物守恒、金额/冷恢复/失败落位/分实例账本、新动作与回合覆盖、3v3前排序。
- 已接参数此前独立110000..110199共200局：五回合均伤144.285、五回合到100为100%、第四回合击杀47%，决策中位36.74ms/P95 205.28ms/最大285.69ms。只作离线模型指标，不是实机胜率或150已达标。
- 记录见[参数、哈希与逐局结果](../benchmarks/2026-11-15-intelligence-live-rollout.json)。新算法的一张前瞻、更多位置候选是可选离线能力，生产固定rollout/64次/单位置候选；本次未继续优化150。
- 未启动/停止main或xiaoli，未操作ADB/Waydroid；框架和MaaPiCli未替换。实际下一局效果仍待实机环境。运行中Agent不热加载Python，下一次启动自动用新策略；未擅自重启现有脚本。

执行检查：`PYTHONPATH=agent .venv/bin/python -m pytest tests/test_intelligence_pool_simulator.py tests/test_intelligence_refresh_strategy.py tests/test_intelligence_gold_value.py tests/test_intelligence_passive_strategy.py tests/test_intelligence_tuned_strategy.py tests/test_intelligence_forecast.py tests/test_intelligence_live.py tests/test_intelligence_simulation.py -q`。
