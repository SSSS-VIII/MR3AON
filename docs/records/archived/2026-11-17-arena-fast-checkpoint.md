# 竞技场：固定板搜索与快速回溯调查

用户调整方向：固定板先用客户端内部完整状态搜索无伤跑法，运行时再用背景、板序和特征定位并匹配操作；随机板保留实时视觉决策，后续识别/策略优化集中到随机板。当前第一优先级是低延迟、可以反复分支的完整回溯，不继续原先的全板视觉调参。

用户明确排除「重开后从头重放」。即使重放一致，成本仍随历史长度增加，不适合大量搜索回退。不要把 reset、传送符、重新定位板子或坐标/血量恢复包装成回溯；不能为了搜索而重写陷阱或大范围改动运行客户端。

## 原客户端边界与已验证事实

结合 Git、原生方法/metadata、恢复 Lua 与暂停实机字段检查：

- 原 `GameRecord` 主要保存输入、种子、同步记录及游标。`StateSynchronize.GameEntityStateSynchronize` 只有 frame/ninjaInfo/bossInfo/extendList；NinjaInfo 为 posX/posY/health/ninjaDie，BossInfo 为 bossHealth。没有查到可直接调用的完整场景存取接口。
- 随机状态不止 Unity.Random：RandomManager 含 random/random_level/random_game/random_block/random_stage/randomSkill/random_boss 等独立 System.Random。角色、对象池、延迟调用、协程、Lua、Unity 原生对象和物理内部状态均需要覆盖。
- 原物理步长仍为 20ms。50ms 暂定采样点不能直接改物理步长；只做观测时可交替推进 40/60ms，累计无漂移。实际 checkpoint 频率留待性能验证。
- 原位内存方案不能只复制堆：2026-11-17 arena 暂停进程采样为 164 线程、277 FD、5392 VMA、RSS 约 1.09GiB，含 `/dev/binder`、`/dev/hwbinder`、多条 `/dev/dri/renderD128` FD/共享映射。普通内存 dump 不覆盖这些内核/图形外部状态。

`arena/Local/rewind_probe.lua` 为显式加载的只读检查模块，未接入 environment/menu，不替换现有 advance；只导出 primitive/enum/vector/primitive-array，遗漏引用逐项标注，`fullSnapshot=false`。`tools/arena_rewind_probe.py` 是已经完成的一次原重开重放诊断，不是搜索 backend，也不是完整快照实现。当前不再继续此路线。

该历史诊断用 seed55200/5级/map43/pin53012，两次共47个可比边界，导出字段匹配0。开场同 episodeFrame22 位置及 random_stage 游标已不同（16/14）；尾步一轮因死亡只推进2/3 tick，另一轮正常，不能称为正常运行时步进超量。两轮死亡方式也不同。检查模块移除、原 advance 身份不变、源码哈希一致，最后通过原流程恢复1101/5000血/暂停菜单/键盘/视觉评估关闭。证据在 `debug/arena-client/rewind-research-v1/native-replay-audit/`。重放速度本身已被用户否决，不再为此修复确定性。

## 快照候选与独立实验

官方资料交叉核对：

- [libTAS 工作原理](https://clementgallet.github.io/libTAS/guides/how/) 有线程暂停/寄存器、内存布局修复及增量脏页；[FAQ](https://clementgallet.github.io/libTAS/faq/) 明确通用真实 GPU 读档不可靠。它不是能直接套到当前 Android/Bionic 客户端的插件。
- [CRIU GPU](https://www.criu.org/GPU_Checkpointing) 的厂商插件不等于支持当前 Android Binder + OpenGL/DRM。未对正在运行的容器执行 CRIU dump/restore，也未覆盖其内存。
- 原 [KVM-Nyx](https://github.com/nyx-fuzz/kvm-nyx) 要求 Intel；本机为 AMD Ryzen AI 9 365，不安装它的内核补丁。
- [Nyx-Lite](https://github.com/nyx-fuzz/nyx-lite) 使用未修改主机 KVM，有基础快照和增量快照树，覆盖客体内核/设备/COW 磁盘。它存在时钟确定性、网络设备和多核限制，仓库 Android 配置不证明当前客户端可运行。

因此先在完全独立的合成 Linux VM 验证「基础状态一次 + 内存脏页/CPU/设备/COW 磁盘增量」的可行性和回退耗时。实验不连接 Android/ADB、不改 InstanceSession、不更换主机内核、不改网络、不迁移 arena；客户端接入尚未实现。未来若需要 VM 后端，应通过命名实例层集成，不能在外部另管 Android。

独立夹具源码在 `tools/arena_checkpoint_lab/`：

- guest 用真实 pthread/futex/TLS、栈和寄存器、64MiB 映射全量 hash、malloc/realloc、mmap/munmap、子进程、Unix socket 待收消息、持有中文件 FD/偏移和 fsync，主动覆盖普通进程内存复制会漏的状态。
- host 计划保存30级增量快照，来回跳转旧/未来节点，重复同操作比较8项状态与完整映射 hash，并试不同操作的兄弟分支。保存和恢复分别计时，执行/64MiB hash/fsync 单独计时，不混为恢复延迟。
- prepare 仅构建独立 rootfs/配置和本地 Nyx benchmark，网络关闭、单 vCPU。依赖/内核/源码与基础磁盘哈希写 manifest，不能拿合成测试结果充当游戏内验收。

**当前结论：增量快照底层已取得毫秒级保存/恢复的实测证据，但原客户端回溯尚未实现，没有新的固定板无伤跑法。** 不能把下述合成 VM 结果写成游戏内通过。

## 实跑结果与时钟缺陷

未修改 Nyx 核心的 1GiB/3GiB 夹具先分别通过132/1100次重复分支检查；3GiB Binder + llvmpipe 组合随后通过330及1100次检查。它们证明已测状态能恢复，**尚未检查计时器，不能据此判断完整性**。原始数据均在 `debug/arena-client/rewind-research-v1/checkpoint-lab-*`，不覆盖失败记录。1GiB 首轮初始化测得406.86ms；完整通过轮基础保存为375.33ms，早先口头407ms对应前一轮测量。

继续加入 CLOCK_MONOTONIC 与 pending timerfd 后，`checkpoint-lab-clock-baseline` 实测基础快照误差 **1,298,309,868ns**，虽然内存/分支检查仍过，最终报告正确为失败。查到两个相关机制：

1. 原 Nyx 在复制全部 RAM 后才采集 TSC/CPU/设备状态，基础 RAM 复制期间经过的约1.3秒被带入状态取时。
2. Firecracker 的迁移恢复沿用 KVM clock realtime 标志。[KVM_SET_CLOCK 官方定义](https://www.kernel.org/doc/html/latest/virt/kvm/api.html#kvm-set-clock) 明确该标志会把宿主流逝时间加给客体；这不符合回溯语义。当前客体 GET_CLOCK flags=14，包含这一标志。

`tools/arena_checkpoint_lab/nyx-rewind-clock.patch` 只修改研究克隆中的 Nyx 外层两个文件，不改 Firecracker 子模块和游戏：在 RAM 复制前抓取时钟/CPU/设备；快照完成后恢复该时刻；恢复时另写 flags=0 的 KVM clock，不添加宿主经过时间。没有把这个补丁注入 arena 或更换宿主内核。

修正后最终两轮均为 **3GiB、单 vCPU、Binder protocol8、客体 llvmpipe、30级增量树**；每轮1100次重复分支检查、1200次同节点恢复、1000次跨节点恢复，均通过。两轮基础磁盘哈希始终未变。恢复含 CPU/设备/内存；游戏逻辑、截图和主机动作链路延迟没有混入恢复耗时。

| 项目 | TSC 中位数 / P95（ms） | KVM clock 中位数 / P95（ms） |
| --- | --- | --- |
| 增量保存（30个样本） | 7.45 / 13.24 | 7.92 / 12.40 |
| 同节点恢复（1200个样本） | 3.96 / 5.52 | 3.60 / 5.00 |
| 跨节点恢复（1000个样本） | 7.92 / 10.46 | 6.87 / 9.30 |

一次性基础保存分别1249.59/1184.47ms，不是每次回溯都复制3GiB。TSC 最大恢复耗时21.25ms、KVM clock 最大11.33ms，不能只报均值而忽略尾部。合成 step 另含64MiB全量 hash/fsync，耗时单列；它没有推进50ms的游戏逻辑。

每轮在第0/15/30个快照专门等待50ms宿主时间后恢复并查询真实客体时钟/待触发计时器。TSC 时钟误差0.271–0.669ms、timer误差0.287–0.682ms；KVM clock 为0.339–1.126ms、timer为0.360–1.137ms，计时器均未提前过期。这仍有执行抖动，不是纳秒级确定性。报告明确 `game_rollback_complete=false`。

最终证据：

- `checkpoint-lab-clock-baseline/report.json`：原版计时失败。
- `checkpoint-lab-clock-fixed-tsc/report.json`、`checkpoint-lab-clock-fixed-kvm/report.json`：修正后两轮通过，含 benchmark SHA、能力、完整日志指标和基础磁盘校验。
- `clock-validation.json`：最终结果门槛再次核验上述三份报告，失败/通过/通过，保留各报告 SHA。
- 每轮目录中保留冻结 C/Rust/准备脚本、Cargo.lock、Nyx 核心补丁、客体/内核/基础盘摘要及配置。研究依赖与命令见 `tools/arena_checkpoint_lab/README.md`。
- 17项离线保护通过，覆盖重放诊断的诚实边界，以及日志假成功、非零退出、磁盘改变、超时、能力缺失、时钟证据缺失、计时器提前过期、误指其它目录磁盘。Python 编译与 diff 检查通过。未运行不相关的全仓测试。

## 当前客户端与接入边界

收尾只读检查 `handoff-native-state.json`：arena 仍是原 Unity2022.3.62f2c1 / OpenGLES3 / 宿主 AMD radeonsi，episodeFrame51、5000血、timeScale0，检查模块已卸载。环境、选关、原 advance 所在源码和既有 runner 的五项原诊断哈希仍一致。实验不接 main/xiaoli，没有新增菜单、修改陷阱、安装内核或迁移现有 arena。

后续接入采用**独立离线搜索沙盒**，同版本 APK/白名单资源/原 GameOnly，通过命名实例层管理，不复制账号；原 Waydroid 环境继续用于视觉匹配与真实操作验收。把 Android Binder、渲染及其服务都留在客体内，不能继续透传宿主 GPU、显示连接或 ADB socket 再称完整快照。客体软件渲染有[Waydroid官方路线](https://docs.waydro.id/faq/get-waydroid-to-work-through-a-vm)，但本次仅验证了合成 EGL/GLES2 pbuffer，不证明原 OpenGLES3/Unity 客户端已兼容。

计划只加受控的物理帧边界、内部状态导出和原输入调用，先在20ms原 tick边界取快照；50ms采样方式及缓存频率随后实测。不逐个重写陷阱/协程，不把反射字段或坐标恢复当作完整性捷径。搜索应先计算候选，再恢复节点、注入动作、立即推进，避免宿主规划时间在恢复后继续计入客体。客体资源预热、硬件随机源、异步载入与时钟抖动对原游戏的影响仍需验证。

当前实测覆盖 vCPU/客体内核/IRQ/PIT/virtio块设备及COW盘；上游网络恢复与PIO/串口输入仍有限制，不应擅自添加到搜索沙盒。Binder 实验只验证设备/协议/context manager/FD，未跑 Android Framework 事务；GL只验证软件pbuffer与像素，未跑Unity复杂材质/纹理/动画。这些都是接入待验项，不能以2200次夹具分支通过替代。

## 后续验收

先取得真实保存/恢复耗时和分支一致性证据，排除无法支撑搜索的底层。完整客户端还必须覆盖对象创建/回收、协程/延迟回调、RNG、角色运动与绳面、伤害、板间切换、死亡和画面恢复；同一快照执行同操作需逐 tick 比较，执行不同操作后能返回原分支。只有这些通过后再开发内部状态决策器和固定板操作库。

之前视觉相关未提交改动保留，不混入 checkpoint 功能。YOLO509 已完成，但没有替换默认，也没有新客户端无伤验收；旧148个长激光目标的最佳框 IoU≥.3 覆盖9→83、≥.5 为2→49，属离线覆盖检查，不是一对一 mAP，不再作为当前优先任务继续训练。

## 原客户端接入续作（开发中，不能视为游戏回溯通过）

用户要求继续到能实际使用，不能停在底层实验。当前新增 `runtime.checkpoint_sandbox.ArenaCheckpointSandbox`，复用 `InstanceSession('arena-search').control()`；仅接受这个新名字，不创建 Waydroid/ADB 连接，不操作 arena/main/xiaoli。新名字私有配置、磁盘、控制 socket、日志在 `.mr3a-instances/arena-search/checkpoint/`。原 arena 源码未修改。新后端、Android 启动器、控制 agent 与内部控制台仍在开发工作区，尚未完成功能验收。

实际进度：共享只读 Android13 system/vendor 镜像已生成私有副本，ARM 翻译文件按系统资源白名单准备；userdata 从空白构造，不复制任何账号。客体内运行 Weston headless/pixman，Android 使用 ANGLE + pastel 软件 OpenGLES，Binder/显示/文件控制都在客体内。已实际启动 SurfaceFlinger、netd、zygote、system_server；package/activity 服务出现，首次启动仍在系统 dexopt 阶段，尚未安装/启动游戏。

接入中已定位并处理的真实启动问题，均属于新沙盒环境：

- Binderfs 子挂载建立晚于 `/dev` 的递归绑定，Android 看到悬空设备路径。调整为设备子挂载全部完成后再绑定设备树；未透传宿主 Binder。
- 启动器 console FD 未关导致 zygote allowlist 拒绝 fork system_server。正确关闭重复 FD，未修改 Android allowlist。
- 简单 chroot 在 Android 后续 mount namespace 中使 trace_marker 的 fd 路径变为 `/sysroot/sys/...`。改为实际 switch-root；软件显示单独保留客体内挂载命名空间，未修改 Android 路径检查。
- 原 Nyx 的 kick handler 依赖未初始化的 Firecracker 私有 vCPU TLS，可能丢失 run 超时。命名 worker 把 kick 绑定到本进程唯一 vCPU 的稳定 KVM_RUN 页，并在请求之间冻结客体时钟；已实测3000ms推进约3016ms返回，原生控制端等待不再让客体自行走时。
- 客体 Fedora 模块化内核缺少初始 dummy/netfilter endpoints：dummy0 与 nfnetlink/nfnetlink_log 在客体中加载后 netd 稳定，system_server 启动。正在补齐外部存储所需 fuse；没有向宿主加载模块。

原 APK 已从 arena 通过命名传输只读取得并核对原 SHA，白名单 AssetBundles/FMODBanks/NCONFIG/Manifest/版本文件约2.2GiB 已复制；未知 `data_*` 文件不复制。payload 内的资源参数密钥私有保存，不输出值。资源 TAR 超过2GiB时本机 mke2fs populate 失败，分为1GiB资源块后私有 payload 磁盘构建成功；不修改资源内容或 APK。

安装阶段准备允许 **仅这个名字的私有 userdata** 用 Sync，避免把初次4GiB以上安装写入都堆在 RAM COW 中；快照/恢复在该阶段必须被 worker 明确拒绝。安装完成后停止客体、切换全部 COW 再进入搜索，不能拿直接写盘实例做完整回溯。

当前新增命名隔离/租约/磁盘配置保护离线通过（同前轮共23项，后续阶段保护仍在增加）。真实 Android 游戏中的保存→受伤→恢复→换操作仍未执行，新决策器与固定板无伤跑法仍未开始。后续必须完成这条实际链路，不能把系统启动或先前夹具数字再次冒充游戏通过。

### 11月18日接入更新（继续开发）

- 真实 Android13 客体已达到 `sys.boot_completed=1`、user0 `RUNNING_UNLOCKED`；SurfaceFlinger 的 renderer 为 ANGLE/SwiftShader OpenGL ES3.1。在完整 Android 运行时保存3GiB快照后设置系统属性并创建/fsync文件，再恢复，两者回到原状态，system_server/SurfaceFlinger仍存活。首次基础保存1075.54ms，**这一轮系统恢复29.57ms**；证据 `debug/arena-client/rewind-research-v1/android-os-checkpoint.json`。这是一次系统层检查，不能当成关卡回溯验收，也不能把之前合成5ms替代这个数字。
- 启动 agent 增加固定 root directory FD：parent 的 switch-root 与 child 通过 `/sysroot` 路径 chroot 原先存在竞态，偶发落入空目录；现在在 fork 前固定目录，再 fchdir/chroot，不更改 Android 本身。agent 在每个命令前加入 PID1 挂载空间；APEX尚未就绪时 Android shell仍无法执行，新传输增加明确就绪等待。
- 安装阶段第一次过早同时做原2GiB APK dexopt，触发 Android 开机权限初始化 watchdog，包管理器 Broken pipe；内存尚有约2GiB available，没有内核OOM。系统服务重启、完成开机后，已核实原APK 2.0.109、primary ABI arm64-v8a安装完成，UID10125。资源白名单约2.2GiB已解包；未复制账号/SharedPreferences，首次启动产生的设置只属于新沙盒。
- 原Unity2022.3.62f2c1已真实启动并显示原隐私提示、随后断网资源提示，真实PNG保留在 `android-game-first-start.png`。临时 Frida16.7.19 standalone injector 附加原游戏时仍会 `Unable to write to process memory: No such process`，游戏自行退出，首例 ApplicationExitInfo 为 EXIT_SELF/status0。无Java调用的no-op脚本也复现，故不能归因于本地Lua或陷阱改动。普通Android Launcher可加载同一agent；独立guest ptrace/INT3检查也通过，与宿主同样返回正确RIP，尚无证据需修改Nyx断点转发。继续比较现有arena已验证的server/native-realm通路，不能宣称已进关卡。
- 安装资源已sync并停机，然后通过持有命名租约的 `set_phase(...,'checkpoint')` 将userdata切回Cow；当前所有盘均Cow，worker报告 `checkpoint_enabled=true`。真实客户端启动现场已可保存/恢复（仍非关卡）：一次增量2.43GiB、1120.75ms，恢复111.34ms；这个大增量覆盖整个app首次启动，不是50ms稳态开销。后续在保存的现场排查，不再每次重开等待。
- 24项现有回溯/命名后端保护离线通过，C以-Wall/-Wextra/-Werror编译，Rust release worker编译通过；未跑不相关全仓测试。新 `CheckpointClient` 仅用于此客体的原文件桥，仍在开发，未替换原arena控制器。新决策器与固定板跑法仍未开始；先完成真实关卡的保存→受伤→恢复→换操作及逐tick一致性验收。

### 真实关卡主线程回溯首轮通过（11月18日，扩大验收仍在继续）

Frida standalone/server native realm空脚本都会使原ARM客户端从Houdini线程exit_group(0)，同快照不附加则正常；不继续修改游戏保护或陷阱。改用Android13 userdebug已有`am attach-agent`：约10KiB原生小桥只通过JNI调用原UnitySendMessage，关闭相同SDK统计重试Looper，没有JVMTI hook、代码补丁或额外常驻线程。Android本来会先用ARM app classloader加载而失败，再以null classloader加载x86 agent成功；没有修改Android框架/签名规则。无网卡的客体停在原CheckPermission1，prepatch Manifest已存在，允许从这个早期状态调用原有本地bootstrap；其余资源/MD5/key/延迟Lua初始化沿用原实现。原GameOnly、音频、level5加载与原画面均已实跑，初次软件渲染加载超过既有60s等待，只延续原加载过程并重挂原wait_ready，没有重开重放。

最初文件RPC会推进暂停下的渲染帧，而下一地图仍异步生成，导致对照random_stage差一位。因此新增独立GameGate：约824字节DEX声明一个native exchange，经JNI注册后，只包围既有MR3A.advance。Unity主线程进入现有Nyx mailbox/EXECDONE时停住整个客体，宿主直接读结果/写动作；检查不再多推进Unity帧。复用现有worker协议，GATE code与延迟到达的root响应严格区分；移交后禁止再通过旧文件接口发root命令，且只允许恢复本gate创建的点，避免把宿主保存的mailbox CR3/地址错误用于gate之前的快照。原advance函数身份检查一直为true，未修改原输入、陷阱、物理更新或20ms步长。

实际首例为疾风第5级、原map42、固定布置stage50012：

- 原1280×720显示中，Unity内部实际1920×1080。第71物理帧主线程停点连续两次只读probe全部相同（包括Unity帧491），下一地图预载已结束。
- 同一快照恢复后推进3原tick（60ms），四次全部导出字段完全相同，含角色、活跃敌人、全部已导出的独立RNG与Unity时钟/帧。原始probe仍是有限观察投影，不是完整状态hash；实际恢复由CPU/设备/RAM/COW盘完成。
- 换跳跃得到原jump14/y1.277163，再恢复，所有已导出字段回到原点。
- 保持16:9将该独立沙盒Unity渲染改为320×180，同一3tick分支的上述原生字段差异0；这里只是首次短窗检查，未宣称所有地图/画质分支均验证。原arena显示/客户端未改。后续40/60ms交替短步用时约0.25–0.56s，多数快照脏页仍约77–110MiB，不能把恢复耗时冒充step耗时。
- 第136帧保存，3tick后原碰撞实际扣血5000→4750（139帧）。从受伤状态恢复实测73.889874ms，真实probe读到136帧/5000血。再次不操作得到完全相同受伤probe；从同点跳跃仍4750，下翻则5000/rollToLineDown3/y0.5531349，随后再次恢复已导出字段完全相同。**保存→原受伤→恢复→改原动作躲过**基本链路通过，无reset或历史输入重放，没有手写血量/位置恢复。
- 此轮其它恢复约40–88ms，3GiB Android29.6ms和合成5ms都不能替代关卡结果。一次从根跨长分支曾141.8ms，尾部尚待统计。一步50ms为原40/60ms交替，不改fixedDeltaTime。

完整结构化证据和冻结C/Lua/Python/Java源码位于`debug/arena-client/rewind-research-v1/native-game-gate-v1/`，原画面`android-game-paused.png`。report的`basic_game_rollback=true`、`game_rollback_complete=false`，明确只有单板基本验收，跨板、对象池/协程生命周期、死亡、长期内存/时钟和新策略还要继续。30项离线保护通过，包含root→game mailbox移交竞态、错误ID、旧agent快照误用、原advance错误不得当成功。

内存实测也暴露必须继续处理的事项：50ms高频增量约80MiB，丢弃旧ID并不会释放仍被子节点引用的RAM祖先。完成首例后已恢复第71帧并丢弃测试分支，避免继续堆内存。正在实现显式RAM新基线（rebase）以释放旧RAM树；保留原客体/磁盘状态、不重开游戏，但当前运行worker尚无该操作，新代码必须编译并独立复验后才能当可用。当前v1 JSON沿用游戏json.stringify，数值数组表现为数字键对象、浮点格式约14位；宿主观察使用一致格式，不能拿它重新构造引擎状态。

### 新基线首次失败与磁盘所有权修正（扩大实测中）

`gate=start_client()`已从只保留安装数据的全Cow镜像自动冷启动原客户端、原GameOnly、音频与关卡并接入gate，未使用一次性Frida或人工SDK路径。新codec沿用原文件桥的17位数值/数组格式。首个3GiB根保存865.99ms，分支恢复28.67ms；初次rebase1088.83ms，静止probe相同，但随后jump导致worker因COW父缓存释放而panic。**静止读字段不能证明rebase正确**，失败日志/源码已冻结`rebase-weak-parent-failure/`，不能据此验收或用重启掩盖。

直接查上游源码：`CowCache.previous`和`CowCacheTree.saved`都是Weak；RAM父链原先同时承担磁盘父层的强引用，丢弃RAM祖先后下一次读取旧扇区会崩。且上游以`saved.len()`分配缓存ID，回收中间ID存在复用风险。当前只在我们的worker维护独立`DiskLayers(Vec<Arc<CowCache>>)`，每次snapshot/rebase留存磁盘层，释放旧RAM图时不再释放所需扇区；未改Firecracker子模块。暂时保留全部磁盘层ID，也避免len-based ID复用。**RAM可回收不等于磁盘缓存长期有界**，后者必须继续统计，不能宣称内存完全解决。

新增Rust真实块读写回归：写两个不同扇区、建立父子缓存、释放原快照拥有者后仍读到两个旧扇区，再多次重定位/改写/取快照，8次均通过。该检查不需VM，也不是字符串断言；会实际触发原Weak父层错误。`cow-rebase-test.log`保留结果。33项Python保护也通过，新增未完成命令不能覆盖/存档、跨agent旧点拒绝、主线程移交后root写入拒绝、新基线旧点失效和剩余RAM不足拒绝。修正后的整机/游戏分支正在复测，仍未验收rebase。

### v4有限整机/关卡验收通过（11月18日）

修正后的`native-game-gate-v4/report.json`最终11项全部true，保留`game_rollback_complete=false`（尚未完成跨板/死亡/长时间边界），不覆盖v2/v3失败报告。v2原生、磁盘及rebase均通过，失败仅为Unity CaptureScreenshotAsTexture返回null；改为帧末Texture2D.ReadPixels读回并恢复RenderTexture.active，物理保持暂停，搜索平时不取图。v3从紧邻受伤点误作为加载基线开始，原生重复分支通过，但“提前无伤推进”前提不成立而失败，未当回溯错误或删除记录。v4从有效较早快照重新检查，全程不重开、不从头重放。

v4结果：同点四分支全部导出字段一致；fsync后的文件内容/未来文件回到原状态；释放旧RAM树后仍可读磁盘、执行相同jump得到完全相同probe；真实136→139帧5000→4750，恢复**48.431043ms**，再次相同受伤、下翻5000；恢复后的320×180 PNG字节完全相同（SHA256 `76e4c15f3895d559df8165c81f4080e30742bf312c319a7bb891a4959763585d`）。原advance身份保持true，角色/碰撞/陷阱源码未改。

12个40/60ms节点增量约76.64–102.40MiB，保存37.13–54.32ms；step另计约0.33–0.59s（含保存的测量），仍是软件渲染较慢的原型。四个同点恢复2.53/25.24/22.96/23.41ms，受伤点48.43ms；不以少数样本宣称P95或长期性能。rebase本轮1710.87ms、使36个旧点失效，仅在重建RAM基线时付出，不是每次50ms回退都复制全RAM。

RSS实测9.2497→9.1564GiB，只下降约95MiB，不能据此说全部旧内存立即归还OS：malloc自由区可能留在worker，磁盘历史层也有独立强引用。当前worker报告232磁盘层/8个RAM点；长期增长与内存上界仍待验证。此处“旧RAM树释放”指已移除祖先所有权和原点失效，仍须后续连续多轮测量。33项Python保护和1项Rust实际块读写回归通过，C以-Werror构建、Rust release构建、Python编译/diff检查通过。

已实现可复现入口：准备好的命名镜像上启动内部console后`gate=start_client()`完成一次原客户端冷初始化；之后`gate.step/snapshot/restore/rebase`是整机内存快照链，不调用reset。原arena/main/xiaoli未迁移，先前视觉WIP保留。下一步继续原对象池/跨板/死亡边界及内部状态搜索，不能把这11个有限检查当成已找到全图无伤路线。

### 跨板和原死亡入口续验（11月18日）

`native-boundary-v2/report.json`的6项检查全部通过：从原50012板第436帧出发，5段各30tick，在586帧实际进入50021板/板序1；整机恢复后每段job、角色/敌人字段、RNG、时钟及活跃敌人InstanceID完全相同。期间确实出现新活跃ID和旧ID退出；恢复后的出口PNG字节一致。此次分支用于生命周期检查，容许原碰撞扣血，不是无伤路线。跨板根恢复52.01ms的手工预验也通过。`native-boundary-v1`保留：其最终帧敌人集合为空，错误地只用首尾集合判断“未生成”，实际上466/496帧已观察到新ID；v2改为检查整个记录时间线，未改游戏生成机制。

`native-death-v1/report.json`的5项检查全部通过：调用原`Ninja.Die(nil,false)`进入`die:31`，恢复后回到活人，重复原Die得到同样有限原生字段及PNG，随后恢复并输入跳跃正常。**这是受控原死亡入口及待执行回调检查，不是自然致死碰撞、完整死亡动画或结算页验收。** 原Die不会替调用者写HP，本例仍2625；不能把它描述为已验证自然HP归零。原方法把timeScale改为.5，首次裸exec因此触发门控暂停断言、等待60s超时；仍可用已知整机快照46.04ms恢复并完整对上原字段。正式检查只在原Die返回后重新设0停车，和原advance边界处理一致，不改Die/陷阱/角色字段。此失败原因和有界恢复应保留，不能用重开掩盖。

宿主`gate.step`新增原tick完成校验：无死亡必须精确走完请求帧数，死亡可提前结束；返回的停点帧必须与job.after相同，倒退/超走/未完成均报错。39项Python保护通过，包括6种正常、提前死亡与错误帧区间。全部在同一arena-search VM内继续操作，未重开/重放；下一步内部状态有限窗搜索，完整自然死亡、长时磁盘/RAM上界仍未完成。

### 原引擎oracle有限窗搜索首例（继续实跑）

新增独立`search.py`，不是视觉策略或自写神经网络：候选直接送入原20ms物理/完整陷阱引擎，通过实际扣血/死亡剪枝；失败只恢复VM父节点，不写HP/位置、不卡无敌，也不从头重放。默认12个40/60ms交替动作区间，选出可存活后只确认前6个，恢复所选真实节点校验原state一致，然后rebase释放旧RAM历史。窗口内DFS可回到更早的动作时刻；确认窗口后放弃旧历史，因此只是有界搜索，不是完整全局穷举。无解或预算耗尽明确停在当前窗根，不把半条路径标成功。完整候选流与实际提交路线分开落盘，记录原地图/板/位置/物理状态、实际tick与restore耗时。没有把新搜索接入旧视觉或修改原arena。

`native-search-v1`实际从map42/stage50012第42帧、x15附近/5000血/非无敌开始：8窗共106次候选、8个扣血分支被拒，48个真正提交区间到第162帧仍5000血。第139帧前临时none/down/jump都伤，自动回到134帧下翻解决；这是搜索产生的动作，不是预设人工跑法。该轮host恢复1.98–45.53ms；每窗12–16分支约21.9–28.5s，rebase约1.3–1.5s，原软件渲染推进仍慢。受控只向控制台PID发送SIGINT，`search_window`将正在试的窗恢复根后保存报告，之后继续同点搜索；不是客户端重开。v2继续从162帧跑，当前尚未到整板出口，不能先称整板无伤。

一次原选板仅作为搜索初始化，未放入回退路径；其原异步重置先超过原60s等待，后续较长advance也报告未完成，最终原场景已进入Running、短步正常，搜索明确从第42帧开始，不把未完成初始化写成成功。未修改选关、wait_ready、原advance或陷阱来掩盖问题，入口前片段不算已搜索路线。

查[Unity原OnDemandRendering说明](https://docs.unity.cn/Documentation/ScriptReference/Rendering.OnDemandRendering.html)后做了快照内性能候选：renderFrameInterval60虽减少渲染，但原协程在不渲染帧不按原边界唤醒，申请3tick实际走了16tick；新步长保护当场拒绝，**不采用**。整机恢复29.66ms后原字段完全一致、间隔回到1，继续普通渲染搜索。失败原生观察冻结`render-interval-rejected/report.json`，不能把独立物理API的文档承诺当本游戏时序已通过。44项离线保护通过，新增多步提前回溯、预算/无解保留根、跨窗50ms奇偶、底层错误不得伪造跑法。

### 固定50012首条出口路线完成（11月18日）

`native-search-v2`继续从162帧搜索27窗到577帧，5000血进入同一原地图的下一板**50022/板序1**（原生重新初始化后第二板与先前跨板验收的50021不同，不能混写）。和v1片段严格逐字段接缝，`native-route-50012-v2.json`得到214个真实提交区间、535原tick/10.7s、13个非none动作，从42帧/x15.160797到577帧/x213.083878，始终5000/非借伤害无敌。初始进入场景至42帧不是已搜索路线，因此`entry_prefix_covered=false`；此结果证明记录起点到下一板的无扣血路线，不宣称所有种子、0帧入口、视觉执行或整竞技场完成。

两轮35个完成窗口共606候选，138个扣血分支被拒；606个搜索restore测得中位2.96ms、P95 46.87ms、最大57.42ms，仅代表这一次搜索中的混合节点分布。出口另做一次原跳跃后恢复，有限native字段和PNG再次完全一致，**这一例恢复124.90ms**，保留慢尾部，不能用搜索分布掩盖。v1受控中断前用211.05s，v2用993.96s，合计约20分钟，软件渲染推进仍是主要成本。51个宿主内存采样（15s间隔约12.5分钟）RSS9.14938GiB基本不变，末尾2448个独立保留磁盘层/12个RAM点；这是有限运行观测，不证明磁盘缓存无限时长有界。

新增`route.export`：逐步校验完整原state、HP、done/error/terminated、实际tick、地图/板上下文及多片段接缝；只导出确认的route，不把失败trial写入标准动作。输出包含板内X、相对物理tick、绳上/下/空中状态、源报告SHA；不虚构陷阱特征或视觉接入，`trap_context_available=false`、`visual_execution_validated=false`明确保留。54项Python保护通过，覆盖真实中断回根、错误接缝/扣血/未完成/跨图/伪出口拒绝。

v2运行期间宿主脚本有后续异常记录与起步检查改进，进程未reload，因此其实际执行版本另存`executed-search.py`，和当时已加载run函数的Python code对象结构相等；`executed_source`记录实际源码SHA和校验结果。末尾按路径复制的`search.py`只是更新后源码，不能冒充本轮加载版本。首次用marshal字节流比较受内部引用共享影响为false，代码、常量、位置及code对象结构逐项相等后改用结构比较，未改变或重跑游戏数据。

出口PNG视觉检查发现**原选板重置把独立沙盒分辨率恢复为1920×1080**，所以v1/v2是在高分辨率软件渲染下搜索，并非始终320×180。此前归档的v4确为320×180，但不能外推到重置后的新场景。当前小试相同3tick把画面重新设320×180后全部原生观察相同，用时1.57s→.44s；正在扩到60tick动作/陷阱分支，未先行宣称长期图形分支均通过。原`Coroutine.lua:coroutine.step`实际返回WaitForEndOfFrame，已从客户端恢复源码再次核实降渲染间隔失败原因。

### 搜索分辨率恢复与60tick对照通过

`render-resolution-v1/report.json`从同一真实577帧VM快照分别在1920×1080和320×180运行20个3tick动作区间（none/jump/none/down/none四轮），合计每支60tick。逐区间job和完整已导出的native投影全部相同，包括藏刃/蜘蛛、角色、RNG和Unity时钟/帧；两支均5000血，实际小图320×180、renderFrameInterval仍1。整支36.7136s→7.36446s，约4.985倍；这仍是有限场景，不宣称所有渲染回调分支均覆盖。

新增`render.prepare`只在独立搜索沙盒中重新请求320×180，拒绝跳渲染帧和非16:9，保留每一帧与原20ms物理。分辨率是Unity延后生效请求，不冒充已经应用，不额外伪造物理tick。`search.run`每个成功窗口确认实际宽高/interval，防止原场景再次静默重置；`boot_client`和现有arena不改。59项Python保护通过，含错宽高比/降渲染间隔事前拒绝、已是小图不重复请求、延后生效如实报告。

正在原位从50022继续`native-search-v3-50022`，没有重置/传送/回放第一板；首5窗577→652仍5000血，明显改善推进耗时。两板间做过暂停截图/性能对照，单独记录新的完整起点，不伪造与上一报告完全相同的render-frame接缝。

### 有限窗搜索按输入次数迭代（50022续作）

50022的旧DFS在687帧陷阱前重复了许多无效晚输入，实际第7窗用92候选才通过；后续仍能到772帧/5000血，并非回溯失效。改为先试0次非none输入，再1次、2次……，同一VM点已经实测扣血的动作不再重复；每个候选的撤销仍为真实节点restore，不改陷阱、碰撞、角色或原时钟。只改变有限预算内的分支次序，不能宣称所有局面必定更快，也仍非全局完备搜索。

新增对抗式离线原型夹具：只有尽早起跳才能安全通过，晚操作都无效。相同100候选预算下，旧次序耗尽100未解、新次序43候选/1次跳跃通过；数据`early-input-ordering.json`明确为**离线夹具，不是原生速度测量**。原生`native-search-v4-50022-ida`从受控中断后恢复的772帧整机根继续，已到1042帧仍5000，出口还在跑。不是从第一板重放。

搜索模块在加载时保留实际源码，run入口立即冻结本轮源码，后续异常记录也不再用结束时可能已编辑的文件覆盖执行版本；v3实际旧源码仍在`executed-search.py`。60项Python保护通过，包含新提前单跳用例和中断/错误不得伪造路线。正在开发的300渲染帧死亡回调检查留工作区，尚未验收，不和排序功能混交。
