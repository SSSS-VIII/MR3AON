# 重开时清理原框架对象池以修复粒子材质和旧Boss残留

## 现象与依据

扩大飞竹测试时，多次后段选板停在Boss段。临时调用计数证明NinjaController/MyFixedUpdate及人物固定更新不再被调用，而通灵兽继续移动。arena原日志明确为EnemyBossBloodNinja.Recycle空引用，经EnemyManager.ActivateOneController/ItemBossController.ActivateBoss打断GameLogicManager固定更新。原Boss血量0/Max1/_dead/AllKilled成立，并非未杀Boss。

用户另反馈品红方块。旧51043/38702原图000102等可复现大面积纯品红粒子；扫描3339幅旧原生图有224幅含>=20品红像素，仅为症状筛选而非全部材质验收。运行时初查Renderer主槽为空220个、其中active+enabled28，Boss_jumpSmoke/_fallSmoke均Unity-null。不能把所有空材质槽都视为错误：ParticleSystem常有不用的第二材质槽和不渲染的父粒子。

## 原因与候选改动

既有reset只回收LevelPoolManager/ItemManager/EnemyManager与InGameResourceFactory的SpawnPool/对象池，没有清BaseFramework.PoolManager.N3GameObjPool。这层持久池跨场景保存敌人与特效；旧BloodNinja id -952874在两次完整原重开后仍在DontDestroyOnLoad、isActive=true、烟雾引用已失效。原GameManager.ClearEnvironmentOld明确先调用N3GameObjPool.ClearPooledObjects(true)，再释放场景/资源。未直接调用ClearEnvironmentOld，因为它还退出登录和卸载全部AB。

在旧场景/旧GameInfo仍有效、原实体回收完成后，补该原生ClearPooledObjects(true)，再DestroyAllPools与ClearAllObjectsInScene。不枚举修改单种Boss/材质、不换Shader、不手写碰撞或人物位置。

## 已验证与未完成

LuaJIT执行真实reset，要求框架池在平台回收之后、资源池/场景/新GameInfo之前且参数true；11项local通过，全部arena407通过、2缺依赖跳过。

热加载后原重开1101：遗留BloodNinja数量变0。后验材质审计主空槽降至29、active+enabled主空槽0。初查完整JSON误被后验脚本覆盖，保留旧症状原图、旧Boss字段JSON/异常堆栈及本次报告计数，不能声称有可重读的完整初查JSON。

随后跨Boss可以继续推进到目标前（不再出现已确认的旧Boss回收停更新），但两次在原mount landingEnd/原LevelManager.isFinishLoad=false处等待，51043块内定位也复现，原因仍待查。不能称选板已全修。已在arena命名入口完整重启，排除修复前失效缓存；未操作main。正在新进程重新触发粒子/截图配对，尚不能称所有品红已解决。


## 新进程复验

只经命名入口./tools/run-arena --restart --paused --seed42 --level1 --no-focus完整重启arena，清除修复前已经毁坏的缓存。先前热加载清掉对象仍遗留的isFinishLoad=false/landingEnd等待，在新进程两轮实际选板未再出现；不手动写isFinishLoad或人物/通灵兽状态来跳过原门控。

新51043/block8随机原操作配对：39131采301帧/12秒，8次jump、6次down，覆盖原绳上/绳下/上下翻/跳落/地面/地面下翻，实际健康5000→2602.16，原受击粒子已触发；全部301帧纯品红像素计数0。退出完整重开1101，再39132原定位与配对，284帧/11.32秒，8种原状态、随机探索最终死亡，284帧品红像素也全部0；此为材质/原操作触发验证，不是策略成绩，更不是无伤。已人工查看修复前000102的大块品红与新帧原受击墨迹/模型/准星/粒子，未用隐藏效果或替换材质消除症状。两轮均完整复位1101/5000血/暂停/菜单键盘/评估关闭。

证据material-clean-v24及material-clean-v24-repeat，源码快照/labels/原图/pixel-review/restored均保留在ignored研究目录。对全游戏所有稀有资源仍不作穷尽保证；本次已复现的品红粒子及反复重开路径通过。正在修复后环境重新进行5/6级飞竹实机计分，不能沿用旧污染环境的无伤结论。


## 后续5/6级扩大画面复核

修后v24-clean、v25-retired、v26-visible共18个实际进入的计分回合，保存原截图3613幅逐帧扫描，纯品红像素（B/R>235、G<35）最大值均0；未进入选板的目录0帧明确不计覆盖。涵盖5101/50013/51043/51091/5009/50091/6011/61081等原场景及重复重开，证据bamboo-safety-v17/magenta-after-wide-v27.json。本筛选用于本次品红症状复核，不代替所有材质正确性的穷尽检查，亦不把这些仍有受伤的回合称为策略通过。
