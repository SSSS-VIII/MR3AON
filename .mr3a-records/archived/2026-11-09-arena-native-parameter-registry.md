# 原生对象参数配对归档

## 需求与原因

静态Cfg查询缺失的226/238/257仍能由原板池生成，不能用配置缺失判为不存在，更不能自行造参数。已有几何标签缺少这些运行时生成配置和实际伤害属性。

## 改动

vision_labels只读采集原EnemyBase._enemyInfo与_enemyBaseProperty，按实际托管对象引用建立每回合递增ID。`parameter_updates`在首次出现时保留原类型和JsonUtility初始字段；后续对象引用ID，避免每帧复制整个自定义配置。每帧另记当前速度、血量、伤害类型/倍率/作用对象，controller白名单加_currentMoveSpeed。角色原god/mounted只读存档。可选诊断失败单独保留错误，不能吞掉原陷阱错误或影响几何采集。

实体说明补257原生证据：3201中EnemyDrinkWarrior/EnemyKill及BoxCollider。检查原ProcessOnTriggerEnter有CompareTag、虚调用、切刀光和KillGameEnemy(self)等，尚未证明角色致死或无害，不能根据类名修改AI/危险分类。

## 验证与未完成

复用正在执行的串行批采，未并发控制设备。新参数版w18三个独立种子各168帧，共6959对象帧，EnemyInfo分别57/59/66份、BaseProperty34/26/30份；检查所有引用均已先定义、ID无重复，序列化/当前字段读取错误 **0**，三个回合god均false。原生快照实际含_enemyInfoCustom、位置/缩放/类型、伤害350等字段。证据在忽略目录`coverage-v6/*w18*/labels.jsonl`及每回合源文件哈希。

这不代表所有资源已采到；当前完整批采仍执行中。缺失原配置家族需要保留快照并在后续导出总目录；尚未把这些特权标签作为部署视觉输入，也未修改原伤害/随机生成/碰撞体。
