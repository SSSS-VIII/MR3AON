# 直冲角色方向与阶段内竖直速度只读复核

## 现象与原版依据

扩大v130的51012唯一250伤为下翻途中撞EnemyStraightBat，不能只从名字Straight推断始终水平。原StateUpdate在一条分支中取GetRoleObjPos减怪物位置、归一化后存0x36c/370/374；冲刺按此三维向量乘速度×deltaTime移动，另一分支用静态方向。原51012的27个蝙蝠放置中9个显式_pointToNinja、4个_followNinjaY，61021的原蓝精灵配置则没有这两项。此前固定水平样本不能概括全部原配置。

v144在暂停1101只读反射确认EnemyStraightBat的ResetEnemyInfo/FixedUpdateMovement/StateUpdate，以及EnemyBase的FixedUpdateMovement/MyUpdate/ResetEnemyInfo hotfix槽均未安装；原动态方向分支需保留，不能强行让所有rush的世界Y速度为0。native actor仍不得读取该放置参数/状态/方向。原始ARM64反汇编和源二进制SHA保存在bat-source-v134.json、bat-hotfix-v144.json。

## 像素研究与边界

当前冲刺X已有独立rush_history拟合，Y继续用混合前阶段的通用历史。v135只在现有已结束v126/v130/v115/v110的35回合像素记录上，按原rush_history的相同时间点取相机校正后Y，使用现有X相同的至少3点/40ms/残差<2px规则拟合阶段Y；无原ID/方向输入，无实时控制修改。原文件SHA及样本完整保留。

2378处接受拟合、13处拒绝；未来缺观测4834个窗口、阶段变化2个窗口不藏掉。80/160/240ms同阶段下一观测的绝对Y误差P95原5.14/7.73/15.79px、阶段拟合4.73/6.86/9.31，P99和最大也降，但中位0.61/.76/1.28→.65/1.01/1.98反而变差。只有下一次已关联像素观测的自洽性，含关联和相机误差，不是原碰撞真值或闭环收益。尚未集成该拟合，不能以尾部改善宣称无伤或已解决这次受伤。

证据在ignored render-readback-probe/{bat-source-v134,bat-hotfix-v144,rush-vertical-v135}.json及脚本；后续需要独立原方向校准和真实同条件对照。
