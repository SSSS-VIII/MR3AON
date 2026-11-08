# 基础小黑参数与观测约定

当前固定疾风竞技场、小黑role1、skin1、level1，按用户最新要求HP为5000（原100的50倍）；运动参数保持原值。下表来自原客户端的NinjaData/prefab及实际运行对象；单位是原世界坐标与秒，不能当成像素。查询当前回合：

```bash
.venv/bin/python tools/arena_local.py parameters
```

| 字段 | 原配置值 | 含义 |
| --- | ---: | --- |
| fixedDeltaTime | 0.02 | 原物理步，50Hz |
| _ninjaHeight | 1 | 角色高度参数 |
| _ninjaFootPoint | 0.75 | 原脚点参数，非胶囊底部 |
| _jumpForce1 | 23.5 | 一段跳初始纵速 |
| _upGravity1 / _downGravity1 | -25 / -9 | 一段跳上升/下降重力参数 |
| _jumpForce2 | 12.5 | 二段跳初始纵速，覆盖当前纵速 |
| _upGravity2 / _downGravity2 | -9.8 / -9.8 | 二段跳重力参数 |
| _normalGravity | -19.8 | 常规重力参数 |
| _rollDownUpSpeed | 8 | 下翻入口纵速参数 |
| _rollAirDownUpSpeed | 28 | 空中下翻入口参数 |
| _driveForce | 5 | 原下冲参数 |
| _climbDistance | 0.8 | 原攀爬距离参数 |

浮点读回可能出现-9.800000190734863等float32表示。原运动分支的重力积分还有3.5倍率、状态选择与部分分支限速，不能直接用表内数值写统一抛物线。当前环境执行原运动函数；独立研究部件的原生指令对照见 [说明](README.md#原生行为研究部件)。

NinjaData还包含三/四段跳及滑翔参数，但基础小黑运行时 `CanJump3=false`、`CanJump4=false`；不能因字段存在而启用。原prefab的_moveSpeed初始值8，运行时会被关卡改写；完整资源下普通初始段曾实测9.5，第4段曾出现12.5、12。以每个观测的 `state.speed`（原GetNinjaSpeed）为准，不能固定成一个全局跑速，也未证明9→9.5的变化来自某个单独加成。

## 碰撞箱

碰撞体随原动画/物理状态切换。Role的普通胶囊local height约1.8、radius0.18、center.x0.1；下翻状态可变为height0.1、radius0.1、center.x0.05。原子物体还带缩放：local height不是world height，下翻胶囊受Unity形状约束后world extents可为0.1。取物用ColliderForItem、骑乘用ColliderAtMount是另外的对象，不能合并成Role受击箱。

`state.colliders` 同时导出类型、enabled/trigger、local center/height/radius/direction以及world bounds center/extents。禁用碰撞体的bounds可能为零。足点、贴地查询与平台承载仍由原角色代码执行，不从画面矩形推断碰撞。

## 地图与时间

`layout` 返回原GameLevelInfo里最终stage/block数据，包含原随机选择后的敌人、道具和板子字段。运行时 `LevelManager._currLevelDataID` 可能指向下一段预载，不能用它代替当前画面所在块。当前疾风竞技场真实mode=6，资源LevelDataType.EndlessGale=6。原GameInfo._combatType getter会把疾风归到公共竞技场3，查询真实模式须用GetRealCombatType；state.mode已使用该接口。

`state.episodeFrame/episodeTime` 是原GameInfo物理计数/回合时间；`frame/time` 是Unity全局渲染计数/时间。reset会经过原开场过程，初始episodeFrame不保证为0，测量步进使用前后差值。60个渲染帧对应约50个物理步；只确认固定步计数与地图同种子复现，尚不保证开场插值、粒子等每像素确定。
