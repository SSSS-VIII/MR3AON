# 报警装置生成的飞竹长激光

## 原生和客户端三方核对

481的53032首伤后多次EnemyFlyBamboo命中，原碰撞事件明确记录Attack BoxCollider长23.670000076294、高.300000011921，center.x=9.6599998474121、scale=1；现有预警只覆盖普通三单位攻击。不能只改球形装置纳入时机或泛称飞竹识别慢。

495/497/498/499反汇编原EnemyAlarm.SummonLaser：构造EnemyFlyBambooDataStruct，renderType=1，传入自身laserAimTime/laserAimLockTime。构造默认分别2/.5秒；FlyBamboo流程另有固定.5秒准备。53032的Alarm配置未覆盖这些默认计时，本次证据不支持“锁定时间不同导致失败”的早先假设，不修改计时常数。元数据496字段顺序、原构造函数和实际几何共同核实，原类型/场景状态不进入actor。

原enemyflybamboo.prefab的控制器列表依次BambooCtrl/Laser/FlySpear/GoldenBamboo：三种长3，Laser长23.67、中心+9.66。原Laser子Attack序列化localX=.55，但EnemyFlyBambooController.Reset会清零attack.localPosition；直接套prefab变换会把原中心多算.55。原Reset代码及受伤事件均确认运行中心+9.66，保留此来源说明和各原文件SHA。新静态注册表为arena/vision-bamboo-projectiles.json，不读取当前板池或敌人配置。

## v500：几何候选与生命周期

新增纯数值arena_bamboo_geometry：原攻击从屏幕右侧+2世界单位发射，以60世界单位/秒前进，保留既有疾风候选最大scale1.3。视觉瞄准标记未证明具体renderType时，对四种原攻击取包络，包含y中心偏移。用最小普通弹体宽度和可能中心区间表示长尾；不把23.67宽度直接套在普通中心上，避免伪造提前伸到角色身边的弹头。

BambooClocks.source_geometry_variants默认False，无新菜单/CLI项。开启时扩展后部危险范围，从最右尾端和最低前进速度推导保留时间约.80秒（另含两原帧裕量），替代.35秒：原保护、时钟回收、预报过滤均使用同一时限。工作区原攻击关联亦使用相同中心包络，避免把新长激光又按旧三单位出生位置缩错时窗。未知形态的包络更保守，可能拖慢规划或造成不必要操作；尚不能称无伤。

默认False保留各自基线，未把工作区原有重叠关联、区间分区、风险权重或reticle改动一并提交；相关适配和完整实跑语义以冻结source快照为准。新模块及注册表加入runner源清单，防止回放缺依赖。12项保护覆盖四形态/两scale/五预测时刻的全部边界、导出的生命周期/旧默认、空观测保留与到时回收、只扩尾不伪造近处弹头。完整竞技场1037通过/2跳过，原生单项配对待跑。

494只读盘点21333帧旧coverage，原Alarm有train299/val294/test296个可见圆框；另发现曲线/直飞共享Smurfs等原模型，不能把原脚本类型直接当可单图识别标签。本轮未训练这种分类头，也未更换YOLO权重。
