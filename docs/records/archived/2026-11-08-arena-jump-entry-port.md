# 基础小黑跳跃入口与效果事件移植

## 需求 / 原因

继续推进全面还原，核对起跳数值的真正施加方式，以及动画以外的效果触发，不能用动画时长代替状态机。

## 改动

ClientJumpEntry移植EnterJump/EnterJump2的基础小黑入口，覆盖增益0x124达到1时不进入、纵速直接覆盖force1/force2、物理状态14/16、不同标志清理，保留音效和烟尘/特殊移动结束事件顺序。明确范围无ItemShell、无滑翔；不把入口函数等同于Jump完整输入/次数判定。

原生执行器增加两个真实函数，按原始LDRB指令解出元数据初始化标志地址，没有修改函数体。上下文包括clone、水面、sync、buff及初始状态；虚方法GetBonus和IsSyncNinja及Unity/效果调用均为显式夹具。实际字段核对：_isClone=0x250、resetJumpTimes=0x2b4、_glided=0x380。效果事件由原始调用读取：一段普通音效101、水面115，二段先烟尘后音效102；非同步一段跳在末尾EndSpecialMoveState(25)。

## 验证

加入80项增益阈值、clone/水面/sync组合及随机起跳速度、初始纵速和标志，对照C#编译运行与原生ARM64指令，状态、float32纵速、标志和事件顺序一致。连同已完成部件共1087项通过。未操作main，未安装系统依赖。

## 继续开发 / 未完成

已核验Ninja.FixedUpdateMovement虚调用顺序包含MoveLogic、UpdateRunDistance、UpdatePhyicsState、LateLogic及地形/镜头/输入清理。原生ProcessMovementOnLine与ProcessMovementOnGround分别3309/3637条指令，空中更新发现gravity*fixedDeltaTime*3.5及部分分支-40下限；尚未核实所有触发条件和速度积分顺序，不把该片段直接宣称为全部状态公式。原生片段保存在debug/arena-client/decoded/ninja-terrain-motion-disassembly.json。下一步继续空中/接触/翻绳完整链和原版渲染；整体模拟器仍开发中。
