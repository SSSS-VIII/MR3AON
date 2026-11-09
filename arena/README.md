# 竞技场本地环境

当前可操作入口使用**原官服客户端自己的Unity运行时**：原模型、骨骼、材质、特效、地图生成、移动和碰撞均由原实现执行。在独立、空白且禁止游戏联网的 `arena` 实例运行，不需要Unity编辑器许可。恢复资源、完整客户端源码与密钥保存在本机忽略目录，不随Git分发。

## 启动和操作

在这台已准备资源的机器上：

```bash
./tools/run-arena --seed 42 --level 4 --paused
./tools/run-arena --stop
```

省略 `--paused` 会直接开始跑；再次运行入口重置回合。`--restart` 重新启动arena游戏，`--cold` 重启arena的Android；`--no-focus` 用于训练时保留桌面焦点。第4段示例便于观察原随机块；默认章节1、第1段、种子1。入口只处理名为arena的实例，复用 `runtime.InstanceSession`，不接管main或复制账号。

| 按键 | 操作 |
| --- | --- |
| K / 空格 / W / ↑ | 跳跃，再按触发原二段跳 |
| S / ↓ | 下翻 |
| P | 暂停 / 继续 |
| R | 相同种子重开 |
| N | 换下一个种子重开 |
| . | 暂停时推进一个原生物理步 |

原屏幕按钮也可直接操作。重开后保持暂停，按P开始。当前基准为疾风竞技场的一级基础小黑，HP为5000，三/四段跳关闭；移动、碰撞、模型和特效仍用原实现。

## 暂停选关

按P打开训练菜单，按「关级 → 地图 → 板子位置 → 版型」选择，再点「从第…块开始」即可进入游戏；「从头开始」从地图开头进入。只含疾风，第8关提供无限段的20种版型。每个位置可固定一个版型，或保留原随机抽取；版型分别标注随机分布、固定布置，动作随机另标。R同种子重开，N换种子重开，都保留当前回合的选择。

点开始后会显示加载状态，完成后直接开始跑，无需再按P。中途位置需要等待行进过程，较远的位置可能耗时较长。初始血量5000，仍会受到伤害；Boss血量1。接口与验证范围见 [选关说明](selection.md)。

## 数据与时序

`Local/environment.lua` 提供原输入、暂停、按种子复位、实际最终地图和运行参数接口；`tools/arena_local.py` 为命令行控制入口：

```bash
.venv/bin/python tools/arena_local.py state
.venv/bin/python tools/arena_local.py parameters > debug/arena-client/gameonly/parameters.json
.venv/bin/python tools/arena_local.py layout > debug/arena-client/gameonly/layout.json
```

物理步为原客户端0.02秒（50Hz），渲染为60Hz；`advance` 按**物理步**计数，输入保持到首个原物理步消费。返回实际物理/渲染帧数，不把截图帧当物理步。小黑参数及碰撞体的local/world区别见 [参数说明](parameters.md)。种子传入原随机函数，最终地图来自原 `GameLevelInfo._stageList`；不自行拼板子。

本地完整提取数据位于 `debug/arena-client/dataset/`，2029张配置表位于 `nconfig-all/`，4813份Lua位于 `lua-recovered/`，157种有配置实体的503包原资源闭包位于 `arena-entities-complete/`（上述路径均相对 `debug/arena-client/`）。恢复方法见 [客户端数据](../docs/develop/竞技场客户端数据.md) 和 [资源恢复](../docs/develop/竞技场原版资源恢复.md)。

## 视觉训练接口

`tools/arena_env.py` 的同步接口接收0/none、1/jump、2/down，返回原PNG、原状态、原分数增量、死亡标记和实际步数。PNG是观测；state/layout是可选的训练标注，不应作为纯视觉策略的输入。每次step结束都会暂停，死亡后必须reset；close只暂停并保留环境。

```python
# PYTHONPATH=tools debug/arena-client/toolenv/bin/python your_script.py
from pathlib import Path
from arena_env import ArenaEnv

env = ArenaEnv()  # 未启动时自动调用本机run-arena，已有环境则复用
observation, info = env.reset(seed=42, chapter=1, level=4)
observation.save(Path('debug/arena-rollout'), 'start')
observation, reward, terminated, truncated, info = env.step('jump', ticks=30)
# observation.image_png: 1280×720原客户端PNG bytes
# info['ticks']: 实际推进物理步；死亡时可能少于请求值
# reward: 原客户端_scoreInfo._totalScore的差值，未增加手工奖励

# 直接训练实际第3关map24的第6块，使用原传送符路线
observation, info = env.reset(seed=42, level=3, map_id=24,
                              start_board=6, boards={6: 31062})
layout = env.layout()
env.close()
```

这是本地环境接口，尚未训练视觉模型或实现自动竞技场策略。动作1/2表示一次原按钮按下与释放；二段跳需要后续再次发送jump。重置前检查种子/章节/关卡范围，并由原NCONFIG校验实际存在的关卡。

## 实测范围

早期HP100基线已验证冷启动、原画面/跳跃/下翻、死亡后复位、固定步与实际地图导出；当前5000血版本另验证K/S/P、菜单选关、版型切换、R/N重放、原传送符专用地图和Boss循环后的真实板内落地。原重开前现显式回收持久池对象，独立复现的旧敌人残留问题已修复。同种子布局复现与换种子路线变化均已实测。初始模型插值可能有微小位置差异，尚不保证逐像素确定。当前仅保留疾风模式；其它角色及每一种随机情况未逐一验收；当前依托Waydroid原运行时，独立Unity工程移植仍未完成。

## 原生行为研究部件

以下C#部件保留用于理解和对照动作，不用于替代上面的原版运行环境。

`Runtime/ClientMotion.cs`已实现空中板子固定步移动、按动画状态切换胶囊参数、小黑重力状态选择与基础一/二段跳入口（含效果事件）。不依赖UnityEditor授权，可用已安装编辑器附带Mono编译运行。

验证将真实ARM64方法放在Unicorn内执行，对外部Unity调用和上下文作显式夹具，然后与编译后的C#输出按float32位模式比较。验证不是把另一份手写公式当作原版：分支、比较指令、原始重力跳转表和浮点算术都来自本地原生库。客户端副本摘要不符立即拒绝。

```bash
debug/arena-client/toolenv/bin/pip install -r tools/arena-native-requirements.txt
debug/arena-client/toolenv/bin/python tools/verify_arena_motion.py \
  --library debug/arena-client/decoded/libil2cpp-runtime-file-layout.so \
  --editor /home/linn/Unity/Hub/Editor/2022.3.62f2c1/Editor \
  --report debug/arena-client/decoded/native-motion-verification.json
```

当前2246例对照通过：220碰撞状态/保护组合、319板子触发/移动/到期案例、468重力状态/四跳标志/参数案例，80跳跃入口的增益门/分身/水面/同步与随机起跳参数组合，303帧基础一/二段跳平地轨迹，400例平台候选查询、152例三组平台合并，304例平台与基础地面高度合并。随机参数使用固定种子1248，另覆盖触发等号、零/负剩余时间、双向移动和未知状态。C#参数均由调用者提供，不把小黑当前prefab值固化成所有角色的规则。

这些独立C#部件的范围与缺失（不描述上面的原客户端运行能力）：

- `ClientCollider`复现的是传给Unity setter的参数及调用次序；PhysX接触形状、变换缩放、触发器及角色搭载还未验证。
- `ClientAirGround`复现的是原生移动更新中的归约部分；原生基类更新、热更、初始边界/生成、回收、碰撞平台和角色承载尚未接入。
- `ClientPlatformQuery`按运行方向保留内部端点次序、排除下穿对象、选择角色下方最高平台；同组等高保留第一个，三组等高选择后组。平台顶面必须严格高于基础地面才成为当前平台；相等时仍返回基础地面。它选择候选，不执行角色承载或落地。
- `ClientFlatFlight`限定无平台/斜坡/额外输入的基础小黑平地跳跃。执行完整原生ProcessMovementOnGround作对照，Unity地形/UI/效果仍使用夹具，不能用于宣称复杂地形已还原。
- `ClientGravity`输入是NinjaPhysicsState，不是NinjaAnimState；只选择当前重力，不执行速度积分或跳跃状态切换。
- `ClientJumpEntry`限定基础小黑、无ItemShell/滑翔；保存音效、空中烟尘和结束特殊移动的事件次序，不等于完整输入判定或效果已渲染。
- 所有外部调用返回值是夹具，不能把本次对照当成全局客户端等价、画面还原或训练环境可用。

资源和整体恢复状态见 [原版资源恢复](../docs/develop/竞技场原版资源恢复.md)。
