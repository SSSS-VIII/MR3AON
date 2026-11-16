# 原资源目录补运行时派生敌人

## 现象与原因

原69个直接放置类型并非所有运行时敌人。8019蒸汽骑士生成153子弹，原实体目录没有它；仅按直接ID解码会把真实碰撞体静默遗漏。

## 具体操作

- 从原CfgGameEnemyInfo定位153，资源名EnemyEliteWarrior_Bullet，配置伤害5，等级后实际伤害另读原生参数；从完整原APK索引定位aa1e669177a280007af90ca97a6831a6.ab。
- 用现有ClientSource/export_recovery读取当前DynamicContent及原APK、验证当前依赖manifest及PatchVersion，原样提取17包依赖、序列化数据和payload。普通用户读取动态目录被文件权限拒绝，随后只读源资源的sudo -n调用成功；没有回退旧动态版本，没有写main数据或接管设备。
- 新arena_runtime_catalog.py依据训练回合原生类型，按原Cfg资源名匹配唯一原Prefab；保留scripts/Collider/依赖及所有输入摘要。无Cfg仍保留raw type，重复歧义配置/Prefab拒绝，不猜别名。
- 输出dataset-ontology.json单独扩充可达类型至70；原selected窗口及真实放置数据逐项不改，不替换正在运行的采集计划。直接放置69、运行派生153分列；不能称完整派生闭包已齐。

## 验证与未完成

原Prefab脚本EnemyBullutFireRobot，与实景一致；BoxCollider原尺寸x0.8/y0.4/z5，当前train-w27有45个可用原平面正标签。17包导出错误0、PatchVersion0431323438一致，静态资源仍标runtime_verified=false，原生生成事实单独native_spawn_verified=true，不能把静态导出当全碰撞语义验收。

3项新保护涵盖精确绑定、缺配置/歧义拒绝、只扩本体目录不改放置；连同数据测试15项通过。后续全批数据构建使用扩展目录，并继续检查其它派生ID、可见未绑定目标，尚未训练含153的完整权重。
