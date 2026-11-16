# 原标注额外导出怪物参数的真实派生类型

## 现象与原因

排查Pinball逐实例反弹时，旧parameter_updates.enemy_infos的initial_parameters里，EnemyInfo._enemyInfoCustom只有基类_render，省略EnemyPinballDataStruct的_acceleratedUp/Down、_reboundSpeedY等。原JsonUtility递归序列化采用嵌套成员声明类型，不能把这份旧JSON当成完整怪物参数。

## 改动

注册enemy_infos原引用时，对实际custom对象单独调用GetType及JsonUtility，新增可选custom_type/custom_parameters，失败保存custom_error。既有id去重、initial_parameters及引用方式保留，不改原对象、不改控制逻辑。此Lua仅原标签采集使用，实时actor不导入或读取这些参数。

## 原生验证

v152原51013平绳两个区段、种子54300/54301，不发操作键，各168帧/10.0166秒，全部god=false，最终HP1500/1877.08；标注/运动校准，不是无伤策略。66份参数引用全部成功，47份Pinball真实参数均为上加速度10、下6、反弹5；另16 Dart、3 Spider也按派生类型导出，错误0。由真实数据确认旧汇总8/8/7并非这些对象的精确值。结束1101/5000、暂停、菜单/键盘开启、评估关闭。

原实例fixture带标签SHA与旧基类/新派生JSON；增加一项直接JSON与RPC两种数组编码的消费边界保护，验证默认0、负值−1和重力10/6/5均保留，旧嵌套字段仍存在。全部arena735通过、2可选依赖跳过。后续只在离线用完整参数分离运动/相机/支撑误差；实时需按像素估计或保留不确定范围，再在5004不同参数上独立验证，完整无伤未达。

ignored证据pinball-motion-v152/{summary,parameter-audit,restored}.json及原图/labels/setup/layout/源副本，collect-pinball-motion-v152.py。原PinballBase运动实现及热更核对参见[物体自身地面](2026-11-10-arena-pinball-own-ground.md)。
