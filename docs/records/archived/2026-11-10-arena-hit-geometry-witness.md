# 受伤后原生碰撞几何见证

## 现象与原因

飞竹候选仍有单击受伤，只记录旧敌人引用/HP无法区分实体框误识别、动作时钟偏差、接触后原响应。用像素估计推测原因不够，需要保留原几何作事后核对，但不能把隐藏状态送入动作策略。

## 改动

仅在已有验收器检测真实HP下降时，读取角色Role与原LastHurtEnemy下当前启用、激活的Enemy标签碰撞器，保存原尺寸/缩放/世界中心和640×360游戏平面投影；另记敌人原_enemyState、角色根位置、相机位置。不扫描全场，不改碰撞或输入；几何异常单独记geometry_error，不丢原受伤记录。动作策略输入和受伤判定仍不使用这些字段。

记录明确标为**受伤之后**的原几何，原hurt响应可能已执行；不据此声称就是Physics触发时刻，也不把未相交的后采样框当作原生碰撞bug。原敌人引用仍可能在环境伤害时陈旧，原scope保留。

## 验证

arena暂停中加载原Lua，手动读取1个Role几何成功，前后timeScale0、HP5000、暂停状态保留，`bamboo-safety-v17/hit-geometry-smoke.json`。三个随后整板均0伤，未虚称这三次验证了HP下降分支。

新的九池批次中38702/51043真实400伤成功写入geometry：enemy_state=flyToNinja，Attack原size3×.2、scale1.3，投影约154×10px；Role为.2世界直径的紧凑Capsule，状态rollToLineDown。字段无geometry_error，可与同回合vision.jsonl按monotonic/曝光时间事后比较。原始证据`bamboo-v20-all-pools-native/l5-51043-s38702/evaluation.jsonl`，解释分析仍在研，不能把400写成已修。

相邻44项飞竹/目标验收保护通过；本功能不改模型/原客户端机制，未接管main，用户暂存任务保留。
