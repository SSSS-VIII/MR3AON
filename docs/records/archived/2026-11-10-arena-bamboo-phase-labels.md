# 原飞竹阶段与配对标注核对

## 现象和原因

第5关5101等飞竹瞄准框被共享Box类别识别，但瞄准时近似静止、发射后换Attack碰撞体；仅延续当前速度不能预测发射时机。此前标签读取_currState，不包含飞竹实际使用的_enemyState，无法用旧数据臆造阶段真值。

## 改动

只读标注增加_enemyState、_aimSpeed、_flySpeed、_lastAttackPos、_lastAimLinePos，沿原继承字段查找与枚举/向量序列化。不改变原敌人、碰撞体、计时、actor接口或现有权重。新增字段只用于配对训练/验收。

## 验证

只读反射确认原枚举aim/aimLock/readyAttack/flyToNinja/insertEdge/none。新种子33000，第5关map41/5101，14秒/3原生ticks步进，421配对帧正常结束，god=false，最终4750血，未开无敌。输出在忽略目录bamboo-phase-v13/train-s33000，反射证据fly-bamboo-reflection-v13.json。

对象帧分布：aim453、aimLock230、readyAttack231、flyToNinja232、none44。观察到aim计时约1秒、aimLock约0.5秒、readyAttack约0.5秒，发射后渲染由Sprite/Outline/Triangle/AimLine换为bamboo1/bamboo2/zhudao_shadow，物理碰撞由AimLine换为Attack，_flySpeed=60/_aimSpeed=4。采样可能跨步，不把首次捕获当作精确状态开始；同一原池ID循环复用也不代表连续同一目标。insertEdge未出现，不能称全状态覆盖。

## 未完成

尚未增加视觉阶段类别或默认运动先验。需结合原状态机及独立val/test配对画面，证明可见预警与攻击碰撞的时空对应，再接标准YOLO监督和预测；不能将原生阶段或世界坐标直接输入部署策略。
