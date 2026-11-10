# 逐次HP下降时保存原版最近受击敌人引用

## 现象和依据

飞竹板已出现多组无伤，但第6关其他板仍有伤，不能从录像形状猜致伤家族。原Ninja元数据及只读反射确认_lastHurtNinjaEnemy为EnemyBase、lastHurtEnemyIndex为Int32。该字段是原生保留引用，环境死亡可能保留更早敌人，不能把它直接当本次伤害的因果判定。

## 改动

现有原生健康采样发现HP下降时，即刻保存帧号、Android monotonic、前后HP、原物理状态及该原引用的名称/脚本/类型ID/索引/活动状态/位置；回合启动清空旧事件。反射异常只记录诊断错误，不中断HP统计或跑图。只读验收JSON增加last_health_drop；actor完全不接收。离线failure_audit仅给时间差0..150ms的伤害窗口附加原始事件，保留引用scope，不改称已证明致伤来源。

## 验证和失败

第一轮34021误用了本Lua未导出的Unity op_Implicit判空，原引用诊断报错，原跑图/伤害统计正常；已改为项目现有对象/gameObject检查。该轮不当成功采集。

固定后新34022第6关map52/6101完整一板，3615累计伤害，god=false/5000上限；保存10个不同原生健康事件，0引用错误，离线8个伤害窗口附上近期事件，8个原引用均为EnemyArrow/类型213。原索引随连续攻击变化，部分池实例ID复用；仍不把保留引用当精确因果，多个快速HP变化可能在低频验收采样之间合并。

3项新时间窗/原引用scope回归、全arena325通过/2缺依赖跳过。文件hurt-reference-v13-s34021（失败）、s34022及failure-audit位于忽略目录。

## 后续调查

原EnemyArrow存在none/active/stay/fly/onGround阶段及_velocityX/Y、_gravity、_velocityAccX；原EnemyArrowWarning为none/active/show/end，预制体无物理碰撞。不能全部按当前速度外推。多次受伤在原slideOnGround阶段，正在原UI重测滑行身体/位移（session59523独占arena）；尚未改滑行预测或箭的部署模型，当前默认仍v13。
