# 按原资源交互语义细分现成YOLO监督与验收

## 需求和原证据

13物理/运动类把水果与危险物合并，无法决定哪些对象可切割。新分类只用核对过的原资源，不以damage=0推广：280香蕉Prefab脚本EnemyFruitMuppet继承EnemyFruitBase，原Box；281/282番茄/西瓜EnemyFruitPinball继承EnemyFruitBase，原Capsule。原EnemyFruitBase触发处理分支切割、延迟EnemyKilled并AddCutFruitNum；200木偶炸弹原Sphere且EnemyMuppetBomb继承EnemySpider，保留危险物。原继承链已在arena反射核对，四种CFG damage/species与原Prefab脚本明确匹配。

## 实现

新增可审阅vision-interactions.json与显式interactions构造参数；原13类默认构造不变，新标准16类只增加fruit_box、fruit_capsule、muppet_bomb，保留旧类别索引、所有原资源目录/四角/形状/参数。配置/脚本不匹配或原形状变化会拒绝构造，不能猜绑或把Capsule/Box硬变球。监督配置SHA进入数据/模型元数据。

标准OBB解码接受高置信slice_target，其阈值存profile（当前0.8）；低置信仍为保守障碍。评分把物理空间、危险物、目标分开；另报原危险物被高置信预测成目标的policy_hazard_as_target，避免空间匹配掩盖危险错分。只按真值原资源算召回，不冒称模型输出原typeID。

## 数据与验证范围

补采训练29000新seed和原训练21003回访，2回合共724原帧；没有用val/test种子训练。原v6/v7/v8/v9合并后**12534训练/6972验证原帧**；果Box1016、果Capsule4169、木偶炸弹183原训练目标，仍69资源有物理正目标/71目录，不能把目录等于验收。独立新val30001/test30002正在补采，未进训练。

5项新保护涵盖原形状保留、零伤害未知物仍危险、错误脚本/CFG拒绝、危险→目标错分单列、低置信退回障碍；连同旧数据/接口31项通过。完整新数据构造成功、可见未绑定0，官方Ultralytics Trainer从v10迁移**标准16类头、8epoch/freeze0/batch16**正在训练，没有自写NN/损失/Trainer。

当前默认权重仍v10。新权重、目标奖励规划和新种子实机尚未验收，不能写成目标识别通过或默认已升级；任务真值始终只在独立记录，不进入部署策略。
