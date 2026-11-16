# 修复漏键后按序号错配回执的虚假延迟

## 现象与原因

v47补跑60011/60021/60031完整穿越，累计4882.5伤，原report的下翻捕获到Unity延迟P95约580ms、最大1022ms，但截图请求P95仅4.84ms、渲染约59.92FPS。检查发现sent down53、observed down52；旧runner按本机key_count与原Input.GetKeyDown累计count相等配对。一旦漏收一次，后续原第n次下翻会被错配给本机上一次按键，造成数百毫秒虚假延迟。不能仅凭此报告认定实际输入队列卡了一秒。

## 改动

新增纯标准库`arena_key_receipts.KeyReceiptMatcher`，只用于评估，不进入动作选择。按每个键前一次原回执到本次原回执的区间寻找自己ACK入队的候选；只有原count连续且区间内恰有一个候选才配对。多个候选、原回执跳采、未知候选或原时钟倒退均显式记录状态，不把第几个键相等当成身份。之后单个候选区间能自行恢复，允许本机key_count与native_count不同。

runner报告保存key_receipt_matching逐项证据，歧义不进入延迟统计；不再用1000ms上限删除真实唯一长延迟。原生时钟仍仅提供后验测量，不影响policy/ACK动作锚点。source清单补依赖。

`arena_board_failures.action_timeline`同步采用区间配对，防止受伤前后动作被同样错移。有ACK但无唯一回执时只标入队时钟，不再借旧报告中可能错配的anchor_error倒推出伪native时刻。确实没有ACK的旧格式仍保留显式anchor来源，边界不扩大。

## 验证

新增5项matcher测试，覆盖漏键后恢复、采样跳count、唯一真实2秒迟延保留、重复/倒序原回执、键相互隔离与未来键不能配对。受伤工具增加漏键后旧anchor不复用的回归；旧合成用例中的回执10.7早于enqueue10.8本身违反因果，改为有效的10.85以继续检验回执优先。22项专项通过。

v47保留原report不覆盖，仅用原evaluation/ACK独立重算：149个唯一配对、1个原回执采样缺口、1个歧义。ACK入队到原收键中位13.895ms、最大24.807ms；这一量与旧host request→Unity/capture→Unity口径不同，不能直接替换同名旧统计。全部区间证据在ignored `key-receipt-audit/v47-causal-interval-results.json`。

随后v48同板两回合原生验证新runner：16/17个回执均唯一匹配、两次无伤穿越。该回合加载的helper源为快照旧候选字段严格取key版；运行中给离线旧日志补了缺key兼容（dict.get），只影响旧格式校验，已加载actor模块不变，但工作区文件SHA因此不同。source-verification明确记录该唯一current_file_mismatch，不宣称结束源码全相符；31份setup与快照摘要均匹配。后续严格新源码验收需再独立运行。

不是对所有历史时延的统一纠正，也不能从回执匹配推断游戏是否接受该动作。原Input.GetKeyDown与成功起跳/下翻仍是不同证据。
