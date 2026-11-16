# 重开及选板后恢复原时间倍率与物理步长

## 现象与复现

核对二段跳首段偏差时，读取到当前Unity及Lua_GameManager.fixedDeltaTime都为0.01，GameManager内部_timeScale为0.5；本地暂停页Unity.timeScale为0。原动作先验的物理步为0.02，不应在未记录的10ms条件下继续调动作补偿。

旧流程受控复现：调用原GameManager.SetTimeScale(.5)后原MR3A.pause，再通过原prepare/native_select完整重开1101。结束仍internal=.5、Unity.timeScale=0、Unity/Lua固定步=.01；恢复开跑仅直接写Unity.timeScale=1，不同步内部倍率/物理步。该残留不因新GameInfo或场景回收消失。证据ignored `render-readback-probe/timescale-reset-reproduction-v55.json`。实验后已原Recover并暂停，未留下0.5。

只读原ARM64核对：GameManager.SetTimeScale(0x4846588)同时更新内部_timeScale、Unity时间倍率、fixedDeltaTime和Lua固定步；小于1的非零倍率按原基准0.02缩放，>=1恢复原0.02。NinjaController.RecoverGameTimeScale(0x4a18578)调用此方法传1。Ninja3BaseObject.MyUpdate(0x4a7ce14)按(time-lastFixedTime)/fixedDeltaTime夹到0..1，在上一/本次物理位置间线性插值；因此运动先验还应区分物理切换与呈现，不能给所有二跳加任意恒定像素偏移。

## 改动

- environment.reset在回收旧回合前调用原GameManager.SetTimeScale(1)，不继承上一回合慢动作步长。
- native_selection在目标板确认到达、交还暂停控制前调用原NinjaController.RecoverGameTimeScale，回收旅行跨Boss可能留下的倍率。
- E.state与后验vision_evaluation记录fixedDeltaTime，runner源码清单补environment/native_selection/arena_local。新字段只供复核，不参与演员决策。

没有直接重写fixedDeltaTime数值，没有更换原物理积分，不改变暂停途中原陷阱或同回合慢动作触发条件。恢复只在新回合/选板边界发生。普通P/K/S与原菜单接口保持原调用。

## 验证

原场景回收LuaJIT夹具补入原时间接口的受控行为，验证旧倍率.5在旧GameInfo回收前归1并恢复.02；该保护及选板相关13项通过。首次全回归发现夹具缺失新原API、已补齐，没有通过删调用掩盖失败。最终全arena642通过、2可选依赖缺失跳过（3.40秒）。

原生`timescale-reset-fixed-v56/report.json`：故意通过原API制造.5/.01残留后，1101重开结束恢复1/.02；六关52地图定位第8板61081（含原通灵兽旅行）结束为1/.02；随后原advance10物理步仍1/.02。全程Unity与Lua固定步一致。最终恢复1101、5000血、暂停菜单/键盘开启、评估关闭。测试记录三份实际加载Lua SHA，全部动作/场景仍走客户端原接口。

## 后续与旧证据边界

v55三次安全1101原UI一跳后二跳间隔约.2/.4/.55秒，各241/241/240帧全为同帧像素码，原生结束5000，render/marker/动作探针对象与全局全清理。事后标准main21像素推理与同码EOF原胶囊比较：可见域二跳10/10、10/10、22/22有框，中心Y中位约1.06/.37/.37px；离开HUD可见域的样本单列，不能叫全程召回100%。这些是在残留10ms固定步下采的校准数据，不能冒充恢复20ms后的动作验收。

v53/v54保存成绩仍保留，不能拿其损血直接当恢复后版本成绩。新v57在恢复后的原20ms条件下重新采三种二跳起点；动作参数仍保持原值，先查旧轨迹是否与新正常时钟一致，再决定是否需要前动作延续模型。
