# 转锤原几何与通用圆弧拟合可行性

## 需求和原版证据

第6关60011仍多次受原EnemyGoldMace/288伤害。原EnemyMace.ProcessState在rotation阶段让根EulerZ增加_speedRotate×GetNinjaSpeed×.125×deltaTime，另一Gear另行反转；原方法FixedUpdateMovement/ProcessState/ResetEnemyInfo保存于debug/arena-client/yolo/finetune/mace-motion-study-v15。普通EnemyMace及EnemyGoldMace prefab都是根Box(.45,1.9)、中心(0,1.4)，并非中心重合的矩形旋转。碰撞框中心应绕根走圆弧，中心到根距离/长边=1.4/1.9。整体缩放不改变此比例。

## 通用像素拟合实验

使用已有标准v13对原val-w12-s21037及val-w25-s21076两回合336帧预测（mace-v13-development），不新增网络。像素OBB角和多帧中心先按可见支撑消除cameraY，拟合水平移动旋转轴+未知偏心向量，比较直线及二次曲线，拒绝短弧、病态矩阵、无偏心、超大半径及明显更合适的抛物线；连续两个一致拟合才启用。两个actor只接收同缓存预测、原像素、时间和自己的已提交按键，完整估计后才接触原对象/碰撞/ID做匹配评分。无原生状态进入动作或拟合。

单拟合固定10点21/288成功，近期10/8/6点窗口增至38/288；加入二次曲线竞争与连续确认后仅3/288。有效样本的短期预测改善不代表覆盖足够。366项回归通过/2缺依赖跳过，包括圆弧正反转、投影组合、中心旋转/短弧/抛物线负例以及失效撤销；仅为实验代码，未启用默认。

## 旧资源全集负例检查及结论

相同v13旧6304图（不新跑第7关）5583完整可见原Box目标帧，两个actor各匹配4666、交集4666，仅30次确认圆弧；该确认均为普通Mace，没有金锤。全配对0.2s的3134预测中心误差中位6.9236→6.9288px、P95同87.0088px，整体没有改善。仅普通Mace被确认的11个0.2s样本中，误差6.91→5.57px、物理IoU .433→.661，样本太少，不能据此实机部署或宣称解决金锤。

报告mace-orbit-v15-{development,legacy-test}保留全配对/覆盖和源摘要。通用hook、额外profile开关、实现与7项实验测试已从实际tools/tests撤回，完整源码保存在mace-motion-study-v15/generic-prototype-sources，不清除失败证据；默认仍已提交v13。未用本实验操作arena，arena保持1101/5000血/暂停菜单/评估关闭。

后续改为严格按原EnemyMace脚本/Box绑定单列现成YOLO类别（两种锤同物理结构），用原中心偏移比例约束旋转轴，再由像素时序选轴方向/角速度。不能把这一物理先验套给所有细长Box；下一轮开发与训练尚未完成，不把此实验记录称新控制功能验收。
