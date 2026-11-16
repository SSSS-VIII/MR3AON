# 坡面刀片的原生运动契约只读复核

## 现象与范围

v80的61071坡面损血全部事后引用EnemyBlade：旧reactive24事件3847.5伤、连续规划27事件4095伤；五关53051相关场也有EnemyBlade。与v79仅一次EnemyHideBlade/EnemyHidePaw的420伤不同，不能把两种原实现混作同一追踪爪行为。原引用可能滞留，需结合每次几何与物理状态，不用引用直接驱动actor。

## 原实现核对

从既有native-all-methods与libil2cpp-runtime-file-layout.so只读解码原方法；完整反汇编和二进制SHA保留在ignored render-readback-probe/blade-source-v86.json，未改原客户端或策略。原函数前有热修复分支，因此另外在arena暂停/无busy时只读反射：EnemyBlade 7、EnemyHideBlade 17、iTween 257个Hotfix静态字段均未安装delegate，见blade-hotfix-v86.json。这一时刻原生方法体实际可适用，不凭反汇编忽略热修复。

EnemyBlade.FixedUpdateMovement在原开关允许且触发后，以当前角、目标角和2×abs(原角色X速度)调用iTween.FloatUpdate，再写回本地Euler角。FloatUpdate原体为current+(target-current)×speed×Time.deltaTime，没有恒角速度外推，也没有读取人物Y计算瞄准角。目标角主要由TriggerFeedback记录当前角并按原Random_Level(5,28)及前进方向偏移；部分原角区间维持当前角。不能将其描述为持续追踪人物位置。

EnemyHideBlade.FixedUpdateMovement调用EnemyBase移动后进自己的ProcessState，另有GrowingOut及出现距离条件；不能直接继承上条EnemyBlade角收敛公式。这里仅核实方法职责，尚未完成所有触发/动画/碰撞边界的原生逐帧校准。

## 模型上的未完成项

当前普通OBB轨迹用平移/旋转短回归，角度低残差就采用角速度，没有像线性Y一样区分测量噪声与显著运动。静止细刀的角度抖动可能被外推成旋转，已触发角度则应渐近收敛。运行类目仍将若干异构盒陷阱合并，不能按原class/ID在实机选预测律；后续先用保存像素/原注释分开的评分核验显著性/旋转包络，再考虑可视觉识别的运动家族。原生字段仅用于此次审计和事后标注。

本次没有实现新角度模型、没有扩大所有碰撞箱，也没有宣称坡面问题已解决。反汇编库在既有debug/arena-client/toolenv（capstone5.0.7）中复用；基础/YOLO环境缺少capstone的两次探测保留，未安装包或替换运行环境。
