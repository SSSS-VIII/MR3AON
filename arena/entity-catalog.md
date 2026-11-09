# 疾风对象、碰撞配置与原生参考图

这一轮按客户端引用建立目录，覆盖已知资源，未将目录覆盖等同于识别验收。所有客户端原件、预览图和配置输出留在忽略目录，没有把它们分发到Git。

## 本机产物

`debug/arena-client/yolo/entity-catalog-final/`包含：

- `entities.json`：157个已有配置的敌人/物品，加5个旧缺失ID；保留原配置、疾风引用位置与资源绑定。
- `prefabs.json`：595个预制体，包括438个共用地面/绳索资源；保留父子变换、脚本、渲染组件、依赖及199个序列化碰撞组件。
- `visual-resources.jsonl`：贴图、atlas/骨骼字节、Mesh、材质、Shader、动画和粒子的原件索引与摘要。贴图预览不冒充已渲染的完整对象。
- `placements.jsonl`、`terrain-layouts.jsonl`：当前疾风目录opening/slots/loop引用的531份板子、7113个块候选，含69种敌人类型、26种物品类型、局部缩放/旋转和自定义动作数据。不混入普通模式板子。

上述地形资源来自438根包的632包闭包，全部导出成功；与既有503包实体闭包按原件摘要核对后合并。版本为dynamicPatch1248。目录数量按当前输入重算，不能直接复用旧报告的汇总数字。

`debug/arena-client/yolo/prefab-references-complete/`包含84幅原生参考图及`gallery.jpg`。不是人工重画：在暂停arena中用原ResourceManager取原预制体，克隆到远处私有图层，关闭行为和接触，通过原材质/骨骼及相机渲染，再完整销毁克隆。主体取原EnemyBase._allRenderObj，避免长蜘蛛丝把身体缩成几个像素。两种纯粒子电球只在克隆上固定种子采样0.25秒，不推进游戏。

`detector-classes-with-references.json`关联参考图、视觉范围和默认姿态的碰撞投影。95个疾风引用类型均有明确状态：84个有参考图、5个无渲染/逻辑对象、3个需要运行时状态、3个当前配置缺失。参考图不是全部动画阶段或检测准确率通过。

## 碰撞的边界

碰撞组件保留Box/Sphere/Capsule等类型、原始尺寸/中心、trigger、enabled、父层级活动状态和完整TRS，不把不同用途组件合成一个“伤害框”。图鉴的框是默认姿态组件投影，不能据此认定实际攻击已开启。

平台/绳索还使用原`LevelBlockCollider`逻辑；实机脚下支撑对象即此类型，没有对应的普通场景Collider。板块端点、地形类型、斜坡、移动板和原实现共同决定支撑，不可仅按主题地面贴图或Prefab Collider判断。

隐藏、伸缩、攻击阶段切换及动态生成的范围仍须用原运行时标注核对。EnemyFlyBamboo预制体中实际包含竹子、激光、飞矛、金竹等不同子节点；默认姿态为空，资源和组件已保留，未把随意激活的子节点当作已验证攻击状态。

旧ID226/238/257仍在疾风候选中，当前磁盘和原运行时NCONFIG.CfgGameEnemyInfo查询无配置；这不表示原工厂不能生成。7008实景已捕获238（EnemyRotateElectricBall及子球），7007捕获226（EnemyDart2Fire），3201捕获257（EnemyDrinkWarrior，C# EnemyKill，BoxCollider），保留原始type、父子归属和粒子画面，未猜测静态Prefab绑定。EnemyKill类名不足以证明其对角色致死或无害，触发语义尚待原逻辑进一步核验。209/210在较大资源计划中缺失但本次疾风无引用。

原生配对标签额外保留按对象引用去重的EnemyInfo与EnemyBaseProperty初始快照，以及当前速度、血量和伤害属性；每回合`parameter_updates`先定义1起始ID，再由对象引用。初始快照不代表后续所有可变字段，当前值另列`runtime_parameters`，可选诊断读取失败显式记录，不丢几何或改原行为。

69个ID是疾风板池直接放置类型，运行时生成物另行核对。已捕获蒸汽骑士生成153（EnemyEliteWarrior_Bullet / EnemyBullutFireRobot），并从当前客户端提取其原Prefab、BoxCollider和17包依赖。`arena_runtime_catalog.py`按实际训练回合与原Cfg/Prefab精确绑定扩充数据目录，保留直接放置与运行时生成的区别，不伪造板池记录。当前扩展目录含70种，完整运行时派生闭包尚未证明。

配对标注schema3进一步保存实际启用的Collider局部参数、完整变换、Box四角、相机矩阵，以及真实支撑端点/隐藏和切换状态。Collider/Renderer只归最近的EnemyBase，电球父对象只持有自身电线Box，子球各持自身Sphere，避免重复合并。纯粒子须有存活粒子才记为可见；这些原生标签仅用于数据和验收，不输入自动跑图策略。

## 复现

读取原件目录生成新目录：

```bash
debug/arena-client/toolenv/bin/python tools/arena_entity_catalog.py \
  --resources debug/arena-client/arena-entities-complete debug/arena-client/terrain-resources-current \
  --output debug/arena-client/yolo/catalog-new
```

arena已运行并暂停时生成参考图；只控制同名实例，完成恢复暂停菜单：

```bash
PYTHONPATH=tools:agent .venv/bin/python tools/arena_preview_assets.py \
  --entities debug/arena-client/yolo/catalog-new/entities.json \
  --output debug/arena-client/yolo/references-new
```

每次输出使用新目录。`state-check.json`核对角色位置、血量、物理帧、模式、暂停状态及场内敌人数；最终整批生成前后均一致。数据来源/脚本摘要另有记录。现成YOLO测试及其失败范围另行归档。
