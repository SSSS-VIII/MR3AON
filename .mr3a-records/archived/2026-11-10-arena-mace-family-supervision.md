# 按原偏心结构单列转锤YOLO家族

## 需求和原版绑定

通用Box的未知圆弧拟合覆盖不足，不能把原1.4/1.9偏心比例套给其他机关。原EnemyMace/EnemyGoldMace同EnemyMace脚本、单根BoxCollider、尺寸(.45,1.9)、中心(0,1.4)，详见[原几何和失败实验](2026-11-10-arena-mace-orbit-feasibility.md)。此功能只准备现成YOLO监督及源物理元数据，不修改网络或原游戏机制。

## 实现

schema/build显式mace_family开关，限定physics taxonomy；严格核验两资源的原EnemyMace脚本、Box形状、唯一根Box和单位local_to_prefab、已核对的尺寸/偏心。变化直接拒绝，不能把同名不同结构套旧先验。physics_profile追加一个mace类别，两个锤共享，原19类索引不变；只将这两原资源Box移至新类，cue仍cue。元数据pivot_offset_ratio和short_long_ratio直接从原几何计算，尚未在推理强制调整框厚度，控制器尚未接入原轴估计。

## 数据和验证

严格沿用v13原train/val整回合及support_band12，data-mace-v15为13827训练/7811验证，转锤2444/1024。对全部21638帧逐字节检查，新mace19映回旧Box4后标签完全一致（共3468个重分类）；其他类别、所有原quad与支撑标签不变。proof存inherited-label-check.json，不使用test生成或补采决策。

4项针对性保护通过：原Mace只追加一类且不改quad、普通/金锤共享类、错脚本拒绝、偏心结构变化拒绝。提交前全部arena363通过、2依赖缺失跳过。

## 当前边界

标准Ultralytics YOLO26n-OBB从原v13继续微调，fit-mace-v15，20类、6epoch、batch16/freeze0/seed17/lr0=.0003/warmup_bias_lr0/warmup1，close_mosaic3，原profile支撑迁移校验先通过。session60453已启动；默认仍原19类v13，没有原生闭环/新权重验收。正在开发按可见框、原偏心比还原双候选轴再由像素时间序列估角速度的分支，未完成，不混入本监督提交。
