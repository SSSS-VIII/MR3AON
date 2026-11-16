# 原伤害模块与武器标注

## 发现与原客户端依据

v346 的五级 53012 死亡回合中，斧兵身体检测框在画面右侧，实际斧头已扫到左侧角色。旧标注只接受 `Enemy` tag，将 `Untagged` 的武器误当辅助触发器；调整身体框或规划余量不能补回这个监督漏项。

原资源 `913323ba8cce4c94d83e42a2fd29e8c1.ab` 的 EnemyPoleaxeWarrior：身体 Warrior 是 Enemy tag；axe 是 Untagged，BoxCollider size=(1.13,2.35,1)、center=(.32,0,0)，同物体存在原 `EnemyAttackModule`，`_belongToEnemy` 明确引用原斧兵组件。原 OnTriggerEnter/ProcessOnTriggerEnter 分派至怪物伤害回调，并非按形状推断危险。纸片预置 `c699a200f35271697d26bbddecc7a8bb.ab` 有同类独立绑定。

离线来源扫描 503 个 bundle 目录，读 662 个文件，确认 2 处绑定、26 个证明文件、0 处已识别但未解析引用、0 处脱离所属怪物层级。此扫描只解析本地 MonoScript/组件引用，没有解析外部 CAB 脚本引用，不能据此宣称所有伤害回调都已穷尽。原反汇编、原 prefab、运行时字段证据保存在私有 `debug/arena-client/yolo/finetune/rope-recovery-v37/poleaxe-source-v349/`。

## 实现边界

- `arena_damage_modules.py` 导出原组件引用证明，规范注册表为 `arena/vision-damage-modules.json`。旧帧补标必须匹配所属脚本类、根预置名、碰撞物体名、碰撞体类型及完整原本地几何；不把所有 Untagged 物体当陷阱。
- 新原生 `vision_labels.lua` schema=5，记录 EnemyAttackModule 的原所属对象 ID。目标生成接受原 Enemy tag 或经过所属核验的原伤害回调；`vision_eval.lua` 的事后命中几何也包含同类武器。均为只读导出，不改原碰撞、伤害、动画或操作。
- 旧冻结 profile 不自动改变；显式 `attach_damage_modules` 生成新版本。新帧回调无需靠静态名字猜测。所有客户端标签仍只用于采集、训练或事后评分，不进入实时视觉决策。
- actor 源快照增加目标生成器和模块导出器，便于下一批验证整批源一致。

## 验证

新增原 prefab 子图 fixture，覆盖原所属关系、无关辅助区、几何/名字/类不符、非法运行时所属、显式 profile 版本以及身体与武器并存。相关 26 项通过，完整 arena 954 通过、2 跳过。

v353 原生只读标注验证：seed=55043，5/map43/start1，pin=53012，共 91 帧，其中 28 帧含原伤害模块、4 帧有可见武器监督；原 axe/Untagged/owner ID/本地几何与资源相符。同帧去掉新回调作对照，确实新增此前缺失的斧头目标。该回合不操作并最终死亡，只证明标注链，不能作为无伤或模型改善证据；数据明确为 `diagnostic_only_never_train`。9 项源哈希始终一致，结束恢复 arena 1101、5000 血、原 .02 步长、暂停、菜单/键盘及 eval 关闭。

## 后续数据与模型，尚未验收

v355 从 main76 原数据集追加武器监督：原 19020 train/9694 val 图像及原标签字节完整保留，65/45 个源 episode 互斥。仅使用原训练源中的 66 张武器正例、原验证源中的 22 张正例；训练正例重复 8 倍，最终 19482/9694 张。验证不重复；没有添加 v353 或任何已检查 actor 回合。20 类原本体、映射均不变，武器仍属于 box_hazard。追加标签由原保存碰撞体的实际变换生成，不扩大身体框。

v356 从 main76 有限 FP32 权重微调现成 YOLO26n-OBB，3 epoch、完整旧图重放、标准 Trainer、低学习率。训练在进行中；后续须核对权重、源划分、独立武器召回、原类别回归和原生避障，不能仅凭训练指标晋升。当前默认模型/策略不变，无伤尚未达到。

私有复现：`build-damage-module-data-v355.py`、`train-damage-module-v356.py` 及日志均在上述 rope-recovery-v37 目录；数据 manifest 留原标签摘要、各源 labels.jsonl 哈希、原组件注册表哈希、逐帧补标依据和生成器哈希。
