# 原客户端竞技场离线环境、操作与固定物理步入口

## 需求与原因

用户要求持续完成可操作且保持原模型、特效、碰撞和随机板子的本地环境，用于后续视觉训练。手写几何模拟及资源工程占位无法满足；当前采用原官服APK与动态资源，在独立空白arena里运行原GameOnly战斗，不依赖Unity编辑器许可。前期失败与底层恢复依据见 [启动调查](2026-11-08-arena-gameonly-bootstrap-investigation.md)。

## 改动

- tools/run-arena → arena_bootstrap.py 固定只控制arena，通过InstanceSession完成启动、恢复、控制租约与关闭；不另建ADB/Waydroid分配逻辑。原APK摘要、本地Lua桥构建报告/仓库桥源摘要一致才启动。新建60Hz、1280×720独立gamescope显示，按本入口参数及PID核验后只聚焦/关闭自己的窗口。
- 冷启动先恢复并核验arena游戏UID的IPv4/IPv6 prohibit规则，现场解析当前Activity别名；等待原Java初始化10秒再使用临时native Java消息，避免初始化过程中附加导致客户端exit0。仅停止Reyun自己的统计重试Looper，拒绝Android主Looper；控制消息确认后detach并按exe核验停止自有server。后续游戏和RPC不常驻Frida。
- arena/Local/bootstrap.lua 在原Unity主线程读本地资源Manifest/MD5，设置原资源key并调用原初始化及完整Lua加载。key从私有文件读取，不嵌入Lua chunk/log。沿用上一提交恢复的原基础属性、FMOD、原地图生成与种子输入。
- advance改按原GameInfo._totalFrameCount计数，物理步0.02秒，50Hz；观测渲染60Hz。按下原操作按钮直到首个实际物理步消费后释放；HP归零立即停止并暂停，不继续穿过原结算。包含物理/渲染计数、原分数/距离、每步轨迹及原碰撞体参数。
- 独立跨场景键盘协程：空格/W/↑跳，S/↓下翻，P暂停/继续，R同种子重开，N新种子，句号单步；屏幕原触控按钮继续使用。reset等待原战斗Running后暂停。
- parameters导出实际NinjaData及原collider local属性/world bounds。运行中的_moveSpeed会被原关卡更新，不能把某次快照当成恒定小黑速度；基础小黑CanJump3/4均false。

## 验证与边界

本轮真实设备验证只在独立arena；main未输入、未重启、未注入。原APK2.0.109及动态PatchVersion1248。实际截图包含原背景、角色骨骼/飘带、障碍、敌人与VFX。旧种子42两次90最终块逐项相同、43变为91块的证据继续有效；尚不宣称渲染初始插值或全部随机效果逐像素确定。

- 固定步实际验证：跳跃30个物理步对应36个渲染帧；再下翻8个物理步进入rollToLineDown；原HP100。LuaJIT执行真实advance代码回归首步释放、50/60计数和HP归零提前结束。
- 真正无输入跑seed43/章节1/第4段，初始物理帧24，推进373步后在回合第397步HP0，状态dieOnLine，接口返回terminated；随后原销毁/新建战斗重置成功，HP100且暂停。截图/状态在忽略目录gameonly/death-reset。
- 原键盘Space经arena自己的ADB事件实测触发jump，没有向main发送事件。
- 首次全新显示冷启动发现gamescope会插入gamescopereaper，不能用直接PPID当compositor。现沿有限父链核验gamescope及本入口脚本参数；回归覆盖reaper链和拒绝其它显示进程。首次失败如实保留，修正后冷启动结果在本记录后续追加。

当前提供的是依托本机Waydroid原运行时的本地环境，并非已完成独立Unity工程移植；此次范围为一级基础小黑、普通竞技场离线战斗。疾风/3v3、其它角色及所有随机地图未逐一验收，也没有训练好的自动跑图模型。专有资源、完整恢复源码、密钥、探针和截图均不入Git。

修正reaper父链后，已执行真实 `./tools/run-arena --stop` → `--cold --paused --seed 42 --level 4`，全新显示及Android会话启动成功，无调试进程依赖。新的gamescope PID3212034由本工具自己的cmdline核验。随后原键盘R重置HP100、N切seed43、P恢复timeScale1再暂停0，keyboardError为空；原1280×720PNG已保存并人工查看（gameonly/cold-launch/original-game.png）。从CfgAudioEventInfo读取正确路径 `event:/Sound/Ninja/Movement/Jump` 后原FMOD描述有效；调查时猜测的Action/Jump路径无效并产生一条人为查询错误，不能据此判定音频缺失。

控制桥/固定步7项、显示父链2项回归通过；最终源码静态检查与训练适配器回归分别记在对应功能记录。冷启动完成后保持隔离arena可操作并暂停，未触碰main。已补充参数说明和运行入口，独立C#部件仍明确其局部验证范围。
