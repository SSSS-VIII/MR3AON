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

按P打开训练菜单，按「关级 → 地图 → 板子位置 → 版型」选择，再点「从第…块开始」即可进入游戏；「从头开始」从地图开头进入。只含疾风，共19张不同地图；传送符入场版本合并展示，第6关保留2张，第8关提供无限段的20种版型。每个位置可固定一个版型，或保留原随机抽取；版型分别标注随机分布、固定布置，动作随机另标。R同种子重开，N换种子重开，都保留当前回合的选择。

点开始后会显示加载状态，完成后直接开始跑，无需再按P。中途位置需要等待行进过程，较远的位置可能耗时较长。选关通灵兽冲刺固定4倍，骑乘时自动吸取飞镖球，落地后关闭这项额外能力。初始血量5000，仍会受到伤害；Boss血量1。接口与验证范围见 [选关说明](selection.md)。

## 数据与时序

`Local/environment.lua` 提供原输入、暂停、按种子复位、实际最终地图和运行参数接口；`tools/arena_local.py` 为命令行控制入口：

```bash
.venv/bin/python tools/arena_local.py state
.venv/bin/python tools/arena_local.py parameters > debug/arena-client/gameonly/parameters.json
.venv/bin/python tools/arena_local.py layout > debug/arena-client/gameonly/layout.json
```

物理步为原客户端0.02秒（50Hz），渲染为60Hz；`advance` 按**物理步**计数，输入保持到首个原物理步消费。返回实际物理/渲染帧数，不把截图帧当物理步。小黑参数及碰撞体的local/world区别见 [参数说明](parameters.md)。种子传入原随机函数，最终地图来自原 `GameLevelInfo._stageList`；不自行拼板子。

本地完整提取数据位于 `debug/arena-client/dataset/`，2029张配置表位于 `nconfig-all/`，4813份Lua位于 `lua-recovered/`，157种有配置实体的503包原资源闭包位于 `arena-entities-complete/`（上述路径均相对 `debug/arena-client/`）。恢复方法见 [客户端数据](../docs/develop/竞技场客户端数据.md) 和 [资源恢复](../docs/develop/竞技场原版资源恢复.md)。

完整疾风引用、地面/绳索、预制体碰撞配置及84幅原生参考图见[对象目录](entity-catalog.md)。目录含明确的缺项与动态状态待核对标记，不能等同于检测器已覆盖全部机关。

## 视觉训练接口

实时视觉入口为`./tools/run-arena-vision --pin 1:1101 --boards 3`，使用微调现成YOLO、运动跟踪和原动作控制，结束显示暂停菜单。默认16类标准OBB已分离水果目标与危险物；新种子随机四板、第三关级三板和原水果80/80均有伤完成，仍未稳定跑完竞技场；当前权重、复现命令、计时和限制见[视觉基线](visual-baseline.md)。下方同步ArenaEnv接口仍供步进和标注使用。

此前YOLOE原资产视觉提示的零样本验收失败；目前改用官方YOLO26n/OBB微调。数据口径、检测结果与历史试验见[YOLO实测](yolo-evaluation.md)。

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

已按[结构化视觉控制方案](visual-control-proposal.md)实现首版识别/跟踪和决策基线；现成YOLO的后续试验尚未通过识别验收，当前没有训练器在运行。[首轮方案](../.mr3a-records/archived/2026-11-09-arena-visual-policy-research.md)已撤回，仅保留测量与原因。迁移过程见[阶段报告](../.mr3a-records/archived/2026-11-09-arena-client-migration-report.md)。

## 内部真值决策实验

`tools/arena_privileged_runner.py` 是单独的内部决策器测试入口，使用命名 `arena` 和原 UI 输入，在每次决策期间暂停游戏；不调用旧整板搜索，不加载视觉模型或已有跑法，也不通过受伤回档修正操作。它供离线专家决策研究使用，不能把步进成绩当作实时键盘部署成绩。

```bash
# arena 已通过 tools/run-arena --paused 启动后，独立测试第一块板。
PYTHONPATH=tools:agent .venv/bin/python tools/arena_privileged_runner.py \
  --level 5 --map 42 --board 50013 --seed 73122 --seconds 35 \
  --output debug/arena-client/privileged-controller-my-run
```

`arena_privileged_state.lua` 只读原角色速度、重力、动作/碰撞参数、敌人实例参数/状态计时、浮台及实际已解析的地形序列。未实例化的后续地形也进入观测，避免把加载边界当断崖。读取不改原角色、碰撞体、陷阱或生命周期。

`arena_privileged_model.py` 使用世界坐标预测动作、支撑接触及障碍危险区间；`arena_privileged_policy.py` 在这些预测上求操作时间窗口，并在模型中检查 −40/+40ms 两个端点。已计划的绝对操作时刻跨后续观测保留，执行前复查当前状态与晚端点；前端点进入过去不等于原窗口失效。这里的端点检查是模型预测，**不是原引擎容差认证**，也不生成可部署的固定板证书。

首版接通直蝙蝠、飞竹、蜘蛛及其已列明的状态。状态转换使用原单精度倒计时和物理更新相位：例如 `.3f` 逐次扣 `.02f`，实际要第16次扣减才小于零。飞竹预备位置与发射位置使用不同原接口；瞄准型直蝙蝠的尚未锁定方向会随候选角色轨迹重新计算。蜘蛛回摆按原20ms步、原 `iTween.FloatUpdate` 乘法顺序和原物理位置插值推进，不能用更小积分步长代替。

角色包括空中下翻、绳上下转换及途中反向、二段跳、下落时碰撞箱恢复和回绳重置跳跃预算；反向下翻的开关/高度阈值直接读取原静态字段。同键重复保留100ms间隔并处理Unity单精度时钟舍入，不同键分别处理，避免把原版可接受的50ms上/下翻压掉。后续已扩展摆钩、弹球、吊锤、曲线/旋转及隐藏刀刃等原状态预测；旋转矩形使用实际四角与角色胶囊扫掠。地面滑铲读取原时长/偏移，保留原三次速度目标、碰撞体父节点前移及恢复；台阶攀爬、滑铲中断、移动浮台激活和部分敌人阶段仍未接通。当前坡面倍率及静态浮台绑定有离线保护，复杂坡面尚未实机验收；观测也不等于完整模拟所有后续生成和随机机制。

独立测试在首次受伤、拒绝决策、越过原生板边界或时限处结束，分别记状态；满血拒绝不算整板无伤。`decisions.jsonl` 保存每次内部观测、提案、实际输入及原状态，`report.json` 保存结果与源摘要，`sources/` 保留实际加载的代码。输入是原 UI 按下后首个物理 tick 释放，尚未等同 Android 键盘的80/500ms脉冲。

```bash
# 默认用该次运行封存的预测器，排除中途另有输入和对象池复用后的对象。
PYTHONPATH=tools:agent .venv/bin/python tools/arena_privileged_audit.py \
  debug/arena-client/privileged-controller-my-run \
  --output debug/arena-client/privileged-controller-my-audit.json
```

审计比较50/100/250/500ms后的原状态，分别报告角色/敌人位置误差和攻击激活不一致。显式 `--model-source tools` 可在同一原数据上评价候选预测器；这是离线对照，不代表候选已在原客户端执行。旧固定板搜索队列继续保持停止，原视觉跑图器与默认跑法库未切换。

2026-11-20最终同源小样本验收如下，均从原生选板入场点到下一板边界；原血量/伤害、`god=false`、`mounted=false`，没有原引擎试动作或回档纠错。不是实时键盘部署、所有板覆盖或逐动作原引擎±40ms认证。

| 第5关地图/板子 | 种子 | 游戏时间 / 距离 | 实际按键 | 结果 |
| --- | --- | --- | --- | --- |
| M42 / 50012 蜘蛛 | 73124 | 11.083s / 204.814m | 18 | 5000血进入下一板 |
| M41 / 51012 冲刺怪 | 73121 | 11.083s / 204.817m | 14 | 5000血进入下一板 |
| M42 / 50013 飞竹 | 73123 | 11.083s / 204.825m | 6 | 5000血进入下一板 |

原始证据位于忽略目录 `debug/arena-client/privileged-controller-v1/`：三个 `*-input-v1-*` 运行及 `progress-summary.json` 核对同源、每个区间/样本血量、无保护状态、零回档。独立壁钟耗时分别约105/102/143秒，单次计算P95仍较高；游戏在决策时暂停，不能据此宣称实时性能达标。25项保护覆盖真实UI轨迹/反向、原蜘蛛状态对、原板尾窗口取消反例和输入时钟边界。

同一原数据的123对直蝙蝠250ms预测，纠正入口距离/单精度倒计时/更新顺序后，X误差P95由6.261m降到0.141m；654对蜘蛛250ms预测的Y误差P95由0.350m降到0.000165m。这些是离线配对误差，不能当整板成功率，飞竹过渡位置仍有尾差。将“后续预测存活时间”放在首位的排序候选使蜘蛛退步，未采用；其失败运行保留。当前贪心选择仍可能进入死路，不把旧候选或少量成功晋升为固定跑法库。

以后接整机回溯时，除Guest外还必须一起保存/恢复宿主决策器的 `scheduled` 与 `last_inputs`；跨前缀沿用绝对窗口或输入历史会破坏因果关系。目前只完成独立决策器，不自动恢复旧搜索队列。

## 独立高速取图

在arena已运行时执行：

```bash
.venv/bin/python tools/arena_capture.py --frames 300
```

默认保留1280×720原画面。Android 13常驻辅助进程调用原显示捕获接口，通过本命名设备的直接数据通道回传RGBA8888；不使用PNG/视频编解码，不连接宿主桌面或合成器截图接口。构建使用本机忽略目录中已有的Android工具，产物留在debug/arena-client/fast-capture。进程及数据通道复用InstanceSession作用域，退出回收自有辅助进程；不改游戏APK或操作菜单。

Python调用为 `with FastCapture(InstanceSession("arena")) as capture: frame = capture.capture()`（从arena_capture导入FastCapture）；`frame.array()`是原RGBA数组视图，带请求序号和捕获时序。该API单独提供，尚未替换上面的ArenaEnv训练接口。请求到整帧数据的实测及长尾边界见[高速取图记录](../.mr3a-records/archived/2026-11-09-arena-native-fast-capture.md)。

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

## 全固定板内部专家搜索（2026-11-20）

用户重新授权后，新增独立队列 `arena_privileged_batch.py`，没有恢复旧 search-v20/finish-v20。分母为疾风343种固定布局、407个合法关卡位置，包含动作随机、奖励、Boss及任务位置。`arena_privileged_catalog.py`连接原配置和预制体依赖；注册预测器不表示所有阶段/子怪/机关已通过验收。所有未建模状态仍明确拒绝，不能通过忽略障碍获得无伤结论。

```bash
# 私有资源与完整VM后端已准备；同名只允许一个worker。
PYTHONPATH=tools:agent .venv/bin/python tools/arena_privileged_batch.py \
  --queue debug/arena-client/privileged-controller-v2/all-fixed-v3 \
  --wall-seconds 300 --defer-certification
```

该队列使用命名 `arena-search` 的现有完整VM回档。每个分支来自内部模型先算出的安全操作窗口；保留窗口中心及两侧仍通过模型−40/+40ms检查的候选，遇到后续死路才回退。VM快照与宿主决策器的计划时刻、分键冷却、路线长度同步保存/恢复；不从板头重放作撤销，也不逐50ms枚举全部按键。`--defer-certification`只产出名义无伤候选，**不是原引擎容差合格证书**。

`coverage.json`逐位置保留每次尝试、游戏/壁钟时间、失败原因及回档次数；`runs/`保留原状态、操作和报告，`sources/<sha>/`冻结实际Python/只读Lua版本。模型只在独立case间整体换版，未完成的分支不混用新旧代码；核心/原生环境变化则安全退出。已原生名义通过的位置继续保留，避免每次补模型都从第一个成功板反复重搜。VM冷启动通过原文件桥加载当前`arena/Local`控制脚本，修正旧资源镜像固定60秒初始化超时的问题；没有重建原游戏资源或更改机关物理。

本轮前三个完整VM原生出口候选为L5/M42/50012、L5/M41/51012、L5/M41/51013：游戏约11.083/11.083/11.067秒，壁钟175/162/148秒，实际回档0/5/3次。另有普通GPU暂停前进的M32/40013曲线板一次5键、8.533秒无伤；不同冻结版本和运行链分别保存，不能混作同源容差验证。目前逐键原引擎端点、新入口及视觉部署验收仍未完成，合格默认库仍0/407。

后续累计保留5个原生出口候选，另两个为L5/M42/5001、50013，壁钟约203/218秒、均0回档；这两个与M41/51013是不同位置。当前后台服务为`mr3a-arena-privileged-fixed-v2.service`，仍使用`all-fixed-v3`队列，日志已续到`all-fixed-v7.log`。新版本优先尝试未覆盖位置，避免补模型后反复重试已有失败；首次遍历并不等于全部位置已成功。原选板可能需要数分钟，保留原900秒上限；仅原选板等待超时、通信已确定且完整VM恢复逐字段一致时，登记失败后继续其他位置，未知传输状态必须停机。

`arena_privileged_family_audit.py`在原前后状态上校验新增机关运动和碰撞范围；真实配对夹具覆盖吊锤、曲线蝙蝠、旋转锤、飞镖、藏刃、摆钩及弹球。摆钩429个短窗位置P95约0.000095米；弹球335个短窗位置P95约0.000045米，补原挤压缩放后包围尺寸P95约0.000009米。统计窗口混合约100/200/500ms，不是整板或全阶段正确性证明。滑铲另有原UI输入/恢复配对保护；完整证据在忽略目录`debug/arena-client/privileged-controller-v2/`。

已继续补精英飞镖原物理样本插值、飞仙非加速阶段、静态EnemyKill及非追踪箭的入土/裁剪。飞镖原生1035/1055个短窗最大中心误差约0.000074/0.000019米；箭用原未裁剪碰撞形状保守包络飞行及入土，522个短窗最大AABB漏包约0.00089米，较大的中心偏差不能称预测准确度。摆钩由画外等待转摆动存在缓存相机时钟的一步差异，原生859对最大点误差约0.162米；规划现在单独扩张角度时钟包络，最大漏包约0.00045米，而不是抹去误差。已知摆动阶段保留原精确积分，不沿用等待包络。

角色方面补原垂直墙/地形死亡阈值，绳下接地板必须提前回绳上；按真实身体父节点X查询坡面，平地不再误用下坡残留倍率。后坡平地100/200/500ms原生轨迹对照误差小于0.0002米；**活动坡面完整加速/父偏移动力学仍待补齐**。非旋转未触发弹簧可按原拾取胶囊与原触发器禁止接触来绕过，接触后的PopBySpring仍不支持。3201独立前进试验因此从绳下接地死亡改善到17.58秒/283.92米/5000血，随后遇到未建模武士停止，不是整板成功。

空间转动导致BoxCollider深度投影进入XY时导出全部八角包围，未实现三维未来变换的移动类明确拒绝。ItemEvent只导出有界原动作数据，尚不忽略或执行其回调。武士武器跟随原Spine骨骼，不能拿静态身体框或攻击触发距离充当挥刀范围；已从原4.0.21二进制资源离线解析49骨骼及动画，但原生阶段/混合动画/武器碰撞配对未完成，仍标记不支持。原始资源及临时Spine工具仅在忽略目录。最新128项相关保护通过，普通arena只读输入烟测的位置、血量、物理状态和游戏时钟均不变；这些不替代全板及容差验收。
