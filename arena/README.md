# 竞技场原版行为移植（开发中）

这里保存从客户端原生方法核对后移植的C#行为。当前是行为部件，尚无完整可操作模拟器。原版纹理、骨骼、预制体和程序副本均保存在忽略目录，不随源码提交。

`Runtime/ClientMotion.cs`已实现空中板子固定步移动、按动画状态切换胶囊参数、小黑重力状态选择与基础一/二段跳入口（含效果事件）。不依赖UnityEditor授权，可用已安装编辑器附带Mono编译运行。

验证将真实ARM64方法放在Unicorn内执行，对外部Unity调用和上下文作显式夹具，然后与编译后的C#输出按float32位模式比较。验证不是把另一份手写公式当作原版：分支、比较指令、原始重力跳转表和浮点算术都来自本地原生库。客户端副本摘要不符立即拒绝。

```bash
debug/arena-client/toolenv/bin/pip install -r tools/arena-native-requirements.txt
debug/arena-client/toolenv/bin/python tools/verify_arena_motion.py \
  --library debug/arena-client/decoded/libil2cpp-runtime-file-layout.so \
  --editor /home/linn/Unity/Hub/Editor/2022.3.62f2c1/Editor \
  --report debug/arena-client/decoded/native-motion-verification.json
```

当前1087例对照通过：220碰撞状态/保护组合、319板子触发/移动/到期案例、468重力状态/四跳标志/参数案例，80跳跃入口的增益门/分身/水面/同步与随机起跳参数组合。随机参数使用固定种子1248，另覆盖触发等号、零/负剩余时间、双向移动和未知状态。C#参数均由调用者提供，不把小黑当前prefab值固化成所有角色的规则。

范围与缺失：

- `ClientCollider`复现的是传给Unity setter的参数及调用次序；PhysX接触形状、变换缩放、触发器及角色搭载还未验证。
- `ClientAirGround`复现的是原生移动更新中的归约部分；原生基类更新、热更、初始边界/生成、回收、碰撞平台和角色承载尚未接入。
- `ClientGravity`输入是NinjaPhysicsState，不是NinjaAnimState；只选择当前重力，不执行速度积分或跳跃状态切换。
- `ClientJumpEntry`限定基础小黑、无ItemShell/滑翔；保存音效、空中烟尘和结束特殊移动的事件次序，不等于完整输入判定或效果已渲染。
- 所有外部调用返回值是夹具，不能把本次对照当成全局客户端等价、画面还原或训练环境可用。

资源和整体恢复状态见 [原版资源恢复](../docs/develop/竞技场原版资源恢复.md)。
