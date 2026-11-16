# 基础小黑平地飞行、顶点与落地的连续原生对照

## 需求 / 原因

继续从独立参数推进到可串联的实际运动，避免恢复了重力选择却仍采用错误倍率和积分顺序。Unity许可未完成不阻碍本次离线行为验证。

## 改动

新增arena_flight_oracle.py，执行完整原生ProcessMovementOnGround方法（3637条指令），约束场景为平地、基础小黑、无空中板/坡度/滑翔/道具/额外输入，Unity位置、地形高度、效果及UI为显式夹具。没有替换或截掉该方法体，不修改运行游戏。原始常量、角色参数由本地资源给出，静态信息按记录版本校验。

C#新增ClientFlatFlight基础跳跃/下落子集，覆盖3.5重力倍率、-40纵速下限、先更新纵速再更新位置、跳14→落15/二跳16→二落17及平地落地。落地采用旧位置与ground+max(foot,abs(oldVy)*dt+0.001)比较，不能用「先积分再钳地面」替代。此部件不支持复杂地形或其它状态，明确报错，不能将平地子集当成整个地形方法已移植。

## 验证

原版参数、小黑一/二段跳，在0.01、0.02和1/60三个固定步长、不同地面高度和水平速度下，共303帧对照完整原生函数，C#位置、速度、物理状态逐float32位模式一致。连同此前部件总1390项通过。调用/上下文中空气板查询返回空，坡度无，重着陆翻滚阈值取高值，完整复杂地形与承载验证没有包含在内。

0.02步长的一段跳示例：首帧vy=21.75、位移dy=0.435；第13号帧（从0开始）转下落，旧位置记录到jumpFromPoint；第34号帧落地并触发原版落尘、音效108和按钮恢复。全轨迹及事件在debug/arena-client/decoded/native-flat-flight-probe.json。setter及其他效果夹具未据此声称Unity画面已验证。

另用UnityPy读取实际APK导出的globalgamemanagers：TimeManager Fixed Timestep=0.019999999552965164，Maximum Allowed Timestep≈0.3333334，TimeScale=1，Maximum Particle Timestep≈0.03；PhysicsManager AutoSyncTransforms=true、QueriesHitTriggers=true。保留完整层碰撞矩阵等到client-time-physics-settings.json。这是序列化配置，运行时覆盖仍待核实，且Physics默认重力-9.81不是角色自有重力。

## 未完成 / 后续

移动板承载、斜坡/绳/天花板、翻绳与完整输入门、运行时动态速度覆盖、原版Unity/Spine视觉、Shader及粒子、整局随机生成仍待完成。继续开发，不把当前局部浮点一致写作完整模拟器或视觉训练环境验收。
