# 疾风选关菜单与原生机制接入（开发中）

## 最新需求

用户确认原手感没有问题，R/N只是重开后暂停。只考虑疾风：暂停菜单按关级→地图池→每个板子位置的版型池选择；HP20倍。后续用户明确：优先复用传送符原实现跳第n关，中途起点用通灵兽冲刺到目标板后落地，清理落地buff；不要直接大改生成。要求独立核查陷阱与原版差异（不依赖用户给症状）、支持K跳跃、竞技场Boss1血、标注同一板子内部的怪物随机/固定。用户睡觉，继续自主完成，不在半成品停止。

## 已完成和实际验证

HP20倍/真实疾风模式已单独提交9c40e66。当前其它选关工作未提交，常驻任务JSON原暂存改动必须保留。

- 新工具arena_catalog.py从CfgEndlessGaleData + 疾风数据提取6路线、30可达地图、238位置、910候选引用/489不同StageID；排除仅用于入场的StageUseFor=1。路线1/2完整，3..6为原传送符跳关路线。最多12位置，菜单分6行翻页。只含真实Gale6。
- 新pause_menu.lua是真实Unity UGUI叠层，沿原EventSystem，原动态字体556，原1280×720画面。已实机点击关级、地图、板子、版型、翻页、开始、继续，P返回菜单均通过。截图gameonly/selection/menu-{selected,risk}.png。默认2000血。
- 实际点地图2/第3块/10032后，map=2且第一Stage=10032；继续按钮TimeScale1/菜单隐藏，P后0/菜单显示；第6关地图52/第8块分页点击也通过。
- 旧开发中的selection.lua使用GetLevelDataID固定地图、GetLoadStageStream缩候选池并裁掉前面板子。这是用户最新指导前的实现，**应改为保留完整地图，通灵兽冲刺寻址**。不得把现裁剪方案当最终实现提交。
- 发现旧元数据里的StageInfoForLevel._appointStageID在当前运行类型没有字段，早期试验因此失败/原客户端回退Stage102。已改成收窄原_stageRandomList；原热更槽通过反射核验nil，不覆盖已有热更。
- 连续重开另发现原预载ThreadPool回调仍写共用流列表，直接StopAllCoroutines会产生跨地图混合；且旧Ninja在Destroy延迟帧仍可能使Game8/Running误判reset完成。environment现异步先等待LevelDataLoading=false，再销毁、初始化/清level buffers；ready必须等待新Ninja身份。LuaJIT回归覆盖两项顺序。
- 当前裁剪方案后续板子不含GameStart事件，曾临时通过原StartGameContent补齐；最新方案通灵兽保留全图应删除这条补事件路径。
- 8个起跑例（1/11033、31/41054、32/40083、41/51093、52/6111、61/7008、71/8000、路线3map24/31062）布局/起点正确，45原物理步后HP2000。4个落差入口6108/6102/2303/22041，最终保留原版出生点及入场后45步也HP2000。证据entries.json、risk-entry-cases.json及PNG在忽略目录selection。
- 尝试额外改_ninjaBornPos到平台，6108发生死亡；UpdateLevelBlock(true,40)试验后角色none停留。已完全撤掉这些额外出生/强制生成改动，并重启arena清理试验状态；当前selection.lua无spawnHook/出生改动，environment无UpdateLevelBlock(true,40)。不要复用该失败方案。
- 最近24项相关回归通过（之后mode6断言/测试小改尚待重新跑），未宣称新任务完成。

## 当前代码与后续工作

未提交：environment重开顺序/菜单调用；pause_menu.lua；selection.lua；arena_catalog.py；arena_local.py上传catalog并加载3个Lua；bootstrap生成catalog及enable_menu；arena_env.py支持map_id/start_board/boards、菜单抑制/清选择；相应tests。K/Boss1/随机板标注/通灵兽/陷阱核查**均未完成**。

最新读取到的原实现依据：

- Lua_GameManager.SetEndlessSkipLevelInfo(skipToLevel)在6023行起，写GameInfo._endlessSkipInfo.startLevel/startDistance等，疾风用CfgRaceJumpOff（Distance1900等）。准备页CurAvatar.isSkipEndless=true、SkipLevel=getEndlessChapterIdBySkip()；Lua_UIMainBg319行调用SetEndlessSkipLevelInfo。
- Lua_GameManager.GetEndlessGaleChapterList414行起：普通完整路线1/2，其余3..6为特定跳关章节。要区分界面第n关与路线中level索引。
- MountController已存在MountBlackDragon，无需另手绘/新建资源。方法参数已反射：RushAtGameStart(bigRush:bool,rushDistance:float)；FlyInLevel(mountID:int,godOnAttack:int,shootAtBegin:int)；EndFlyInLevel()；EndMountSkill()。RushAtGameStart已有原Lua热更修正z层级，**必须保留，不可覆盖**。MountBase.RushEnd()、StartLanding(isRestartLevel:bool)可用；需追原落地/距离及buff清理。
- EnemyBossBase/EnemyBase提供原SetHealth(int)、_currentHealth setter；MaxHp只读，另有InitBonus(CfgBonusType,...)/CurrentHp，适合把Boss当前血设1，需保留原死亡/分阶段流程，尚未实施。
- 同一Stage随机性并非“池里有多个Stage”。疾风646份Stage静态扫描：内部块组均只有一个候选，重复min/max无差；怪物custom参数大量_randomRangeY、_rangeRandomY、_randomSpeedRotate、_randomRotateDir。原生runtime分支/default值仍须核实，正数位置范围可标随机分布，单独方向/速度可标随机动作；无证据不要全部标固定。
- 陷阱核查方向尚未确定：目前原资源/组件执行，未写替代陷阱，但GameOnly分支、裁剪丢上下文、暂停仅TimeScale0与原PauseGameContent差异、池复位都需审计。原Lua_EnemyManager.IsOfflineGame用于本地模拟，NPC部分有GameOnly分支；Lua_GameManager.NeedOverrideNinjaAnim7347在GameOnly返回true。不得凭猜测打补丁。需要采集具体原行为证据。

## 设备/工具

只控制InstanceSession("arena")，main未操作。当前arena是第二次新的原客户端进程，最后停在暂停菜单（草稿选第6关map52/第8块，实际当前回合map2/10032）。没有进行中的长设备脚本。新运行后原临时Frida已退出。除常驻任务JSON外都为本轮未提交文件。Native方法/字段反射存selection/mechanism-types.json；原ARM方法表decoded/native-all-methods.json，库decoded/libil2cpp-runtime-file-layout.so，capstone在toolenv。所有专有数据留debug。

## 用户要求回退后的处理

用户随后报告跳跃/下翻/暂停输入与界面消失，明确要求回到选关前再按轻改动原机制实现，并将HP设5000。已把上述全部未提交选关/菜单代码和diff归档至debug/arena-client/gameonly/selection-reverted-2026-11-09，六个已跟踪代码/测试恢复9c40e66，五个本轮新增代码/测试从工作源码移除；未撤销已提交的疾风切换。当前只在该基线上增加5000HP与K键，并通过完整游戏进程重启清掉裁剪热更/UGUI/旧协程，不把旧实现留在运行时。后续跳关仍需按原传送符和通灵兽重做，本文之前的裁剪/菜单验证仅为已撤回试验历史。
