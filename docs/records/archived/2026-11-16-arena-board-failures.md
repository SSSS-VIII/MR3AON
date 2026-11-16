# 疾风逐板失败证据的离线审计

## 需求与问题

后续需要对每种普通板逐一筛查失败，保留原阶段、受伤前后画面和输入依据。此前整回合 `final.damage` 只能说明回合总损血；多板回合不能把总伤害平摊到各板，也不能把进入最后一块板或进入 Boss 地图当作该板已完成。

原 `arena/Local/vision_eval.lua` 在血量实际下降时保存 `last_health_drop`，但后续采样会持续返回同一个事件；只按每行统计会重复计算。若两次受伤发生在相邻原生采样之间，后一条引用还会覆盖前一条，所以仅有事件列表也不保证完整。原累计 `damage` 按每次下降累加，途中回血不会减小它，不能以初始血量减最终血量替代。

另一个时间边界是 `vision.jsonl`：`time` 属于外推后的决策状态；原画面时间要扣掉 `observation_age_ms / 1000`。`report.actions.request_ns` 是宿主时间，不能直接与原 Android monotonic 相减。已有 `arena_failure_audit.py` 未覆盖这些逐板及持久事件边界，本次新增独立工具，不改旧入口或在线运行器。

## 实现

新增 `tools/arena_board_failures.py`，只使用 Python 标准库读取现有 actor 目录中的 `setup.json`、`report.json`、`evaluation.jsonl`、`vision.jsonl` 和截图路径，不导入策略、设备、推理或 GPU 代码，也不启动游戏。

- 要求真实 actor 的 initial/final/actions/board_entries/status 结构，拒绝 observe-only、采集头文件和损坏的 JSON。原图仅链接，不编辑。
- 按原事件的 monotonic/frame/before/after 去重，保留引用次数、原始物理阶段、原受击几何和引用来源。初始时间之前的残留事件另列，不算本轮受伤。
- 以事件时刻前后的原生样本定位板归属。两侧原 map/stageIndex/stageID 一致才列 `attributed`；跨板或进入尚无 stageID 的新 Boss 地图列 `boundary_ambiguous`；缺失支撑阶段等情况列 `unresolved`。保留两侧完整阶段信息、候选板及采样间隔。原 stageIndex 为零起始索引，不混作菜单板号。
- 板上只累计已经见证且可归属的事件损血；不确定事件单列。对比原累计损血，明确列出未见证差额、事件总额超过原计数、计数回退等问题，绝不制造缺失事件或平摊伤害。
- 按还原后的画面时间给出最近观测、最近实际保存的原图/overlay、受伤前最近原图和时间误差。画面对应记录中的 phase/jumps 仍是决策时的预测状态，字段明确标注 `at_decision`，不冒充截图时原生状态。没有观测龄期的旧记录不猜时间。
- 输入优先使用原 `keyReceipts` 的按键编号和时间；原回执被后续覆盖时可由记录中的 committed anchor error 还原原回执时间；再缺失则明确标成 enqueue 时间，不能称 Unity 已接收。只有宿主 request_ns/elapsed 的旧输入列为未知时钟。保留最近前后输入、前 600ms 输入以及提交的动作 primitive。
- 保存四个输入文件 SHA256、actor 当时记录的源 SHA 和模型信息，便于复核历史版本。原保留敌人引用可能来自之前的敌人，原受击几何也可能已被受伤反应改变；工具只保留这些证据，不据此直接宣判伤害来源。

输出只包含本地 JSON 和简短计数；文件用独占创建，拒绝覆盖原报告或既有审计。多个输入目录去重，单个目录失败明确列在 errors，CLI 返回非零。没有增加游戏菜单选项。

```bash
.venv/bin/python tools/arena_board_failures.py \
  debug/arena-client/yolo/finetune/rope-recovery-v37/native-fork-v39/l6-61081-s39203 \
  debug/arena-client/yolo/finetune/rope-recovery-v37/native-fork-v39/l6-61081-s40200 \
  debug/arena-client/yolo/finetune/rope-recovery-v37/native-fork-v39/l5-51043-s40201 \
  debug/arena-client/yolo/finetune/rope-recovery-v37/native-fork-v39/l6-6011-s40202 \
  --output debug/arena-client/yolo/finetune/rope-recovery-v37/board-failures-v39/final-audit.json
```

## 验证

对封存的四份 v39 actor 记录运行工具，得到 4 回合、0 读取错误、3 次唯一原生受伤，累计 1360；未见证损血差额和无法归属损血均为 0。反复出现的受伤引用分别为 76、38、56 条，去重后各只有一次。原生事件周围的阶段采样间隔为 116.878、124.593、114.311ms，三组两侧均为同一块原板。

| 原回合 | 原报告 | 唯一事件阶段 | 最近保存原图及相对受伤时间 | 前一次 Unity 输入 |
| --- | --- | --- | --- | --- |
| 61081 / seed 39203 | 完成，损血 480 | jump:14 | 667，+26.280ms | jump1，提前 25.882ms |
| 61081 / seed 40200 | 完成，损血 0 | 无事件 | 不适用 | 不适用 |
| 51043 / seed 40201 | 完成，损血 400 | runOnLine:1 | 259，−68.740ms | rope_up，提前 270.804ms |
| 6011 / seed 40202 | 完成，损血 480 | jump:14 | 355，−64.961ms | jump1，提前 52.756ms |

最近观测帧分别是 666/260/356，与最近保存原图不是同一组，因为录图约每 100ms 保存一次。工具同时给出两者和受伤前原图，没有把受伤后的画面当作事前检测结果。这些关联用于定位进一步回放的窗口，不足以单独判断某次跳跃就是失败原因。

新增 `tests/test_arena_board_failures.py` 的 16 项 CPU 测试，覆盖持久事件去重、原阶段归属、跨板/Boss 地图歧义、缺失支撑、回血后再次受伤、被覆盖的事件缺口、初始残留、截图/决策时钟区别、缺失原图与时钟、原按键回执/宿主时钟分离、计数异常、材料/observe 拒绝、零损血不扩大验收和拒绝覆盖原证据。执行 `PYTHONPATH=tools .venv/bin/python -m pytest tests/test_arena_board_failures.py tests/test_arena_board_audit.py -q --tb=short`，共 34 项通过；输出保存在 ignored `board-failures-v39/tests.txt`。`git diff --check` 通过。

本轮只复核已有文件，没有重新操作实例、训练模型或更改在线动作/预测源码。四回合属于上翻反向下翻补充之前的 v39；不能当作后续 reverse-v40 或当前全部代码的无伤验收。逐板完成及当前源码一致的覆盖仍由 [逐板清单工具](2026-11-16-arena-board-audit.md) 判断；本工具中的某板零已见损血不是该板已完成、所有随机种子无伤或全版本验收。
