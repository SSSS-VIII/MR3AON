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

### 第二条固定板路线与300帧致死恢复通过（11月18日收口）

50022续作完成：v3确认577→772，v4按输入次数搜索772→1327，严格原state/板上下文接缝后得到`native-route-50022-v1.json`，300区间/750原tick/19个非none动作，始终5000血进入50031/板序2、x490.5802。第二板两轮49个完成窗口、1494候选、355扣血剪枝，165.34+541.41秒；不是所有窗口都因排序变快（最难窗口189候选），保留实际结果。第一板214区间/13动作、第二板300区间/19动作，两板各自记录起点至出口均通过。两板间有暂停截图/分辨率对照导致render frame变化，因此不把两个独立起点报告伪装成严格连续的全渲染帧重演。

`native-route-index-v1.json`收录两份标准记录的SHA、起止帧/板内X和原catalog分类证据，两者原分类均fixed。第一板入口前42帧、第二板入口前约1.08m未作为搜索片段覆盖，`entry_prefix_covered=false`如实保留。视觉匹配/实际视觉部署仍false。v3实际执行源码与此前保存run函数code结构相等，v4开跑时冻结源码与实际加载字节一致。

新增`lifecycle.run_death_frames`验证原死亡后继续300个渲染帧：

- `native-death-300-v1`直接原Die，保留原.5时间倍率，实际die31→dieOnLine32，到第1578原物理帧；重复分支的状态轨迹与PNG一致，恢复43.60ms后回1327/5000、原生字段一致并能跳跃，4项检查通过。由于直接Die未扣血，这一例不是致死伤害。
- 反射只读确认原`DamageSelf(Single value)`接口后，在整机快照内调用`DamageSelf(MaxHp*2)`，原方法实际5000→0、触发原Die；即时恢复13.36ms并全部已导出字段一致。没有手写HP/位置/无敌、没有修改DamageSelf或其它游戏方法。
- `native-lethal-300-v1`从同一活人点重复原DamageSelf致死并继续300渲染帧，两支均0血/die31→dieOnLine32，最终字段轨迹及PNG一致，恢复**57.113392ms**回到5000血/runOnLine，跳跃成功、所有已导出native字段回到保存点；5项检查全true。仍为受控原生致死，不冒充自然陷阱致死。

该GameOnly现场两轮最终均仍为content Running，不能把300帧测试说成已验完整结算UI。`game_rollback_complete=false`继续保留；自然陷阱致死、所有生命周期、长期磁盘缓存有界、全量板库与视觉执行仍有后续。60项离线保护与Python编译/diff检查通过，原arena/main及此前视觉WIP未改。最终arena-search仍停在1327帧/5000血/runOnLine、原advance身份不变，4个RAM点/7456个保留磁盘层；RSS约9.15GiB，有限两板运行没有线性RSS膨胀，不当成无限时长保证。控制台仍持命名租约，退出才关闭VM/丢RAM点。


### 全固定板队列与视觉接管开发中（11月18日续）

用户要求跑通全部固定板并接原视觉跑图器。原疾风catalog去掉入口传送符别名后19张地图，含末关loop池共343种固定布局、407个关级/地图/板序场景；不能沿用未计loop的327分母。固定布局不代表怪物运动完全确定，motion分类继续保留。新增canonical inventory/出口判定/持久队列；原native_select只初始化新的搜索案例，窗口内撤销仍全部整机restore。跨地图只承认原末板后出口；loop还要求新实例和StageStartX前移，末关原生循环仍待验。

原位继续50031从1327→1502帧，70区间/0输入保持5000；后继50043亦搜出558区间无伤出口、64参考图，但原205._rangeRandomY将其归为随机板，**不计固定板通过**。队列另完成50012重新采图32张，以及51012、51013、5001；截至该条记录6/407原生通过（50022/50031旧记录待补参考），detector_verified和live_runner_verified仍0。进度与逐轮失败见debug/arena-client/fixed-route-work/batch-all/coverage.json；队列还在同一个arena-search命名租约内运行。50013搜到第25窗因rebase安全内存检查中止，未计成功；后续51073初始化较慢但最终进入原场景，仍搜索中。

collector复用原vision_labels，只在选定整机快照的临时分支截图/读取布局，始终恢复后核对完整已导出state；图片不得推进物理帧。实测.NET Base64解码+Encoding.GetString曾无错返回空串导致observer没有安装，旧失败证据保留；现改Lua字符串350字分块并断言源码非空/函数存在，LuaJIT含中文/转义长串回环通过。原search/route增加原生出口证明及截图状态复核，不修改原advance/陷阱/碰撞/时钟。源码按开跑时冻结，未将失败试验伪装为路线。

视觉接管原型单独开发：现有YOLO检测的静态前景锚点+背景ORB判关级/地图/板序，维护板内X、展开块序、循环visit和不确定度；重复图案保留竞争假设，随机/未定位/姿态不符退回原MPC。只读native标注仅在离线atlas编译器使用，运行匹配器不连接client/evaluator。atlas-v4共913图/14场景，来自新原生参考及既有录图，不是全板库也不是独立测试集。修复npz懒加载每候选重复解压的500–850ms开销，预热后匹配约5–8ms。

原arena实机50012同seed两轮：v1穿越有2次受伤/仅1次固定动作，v2持续身份不再跳到第四板但仍7次受伤，绝不宣称视觉无伤。v2固定接管139帧、余下实时策略；板内X与动作阶段衔接/按键链路偏晚需继续定位。native原生通过不自动填成live通过。产物live-hybrid-50012-v1/v2保留evaluation/vision/setup/图片；原arena每轮finally恢复暂停菜单。旧实时策略其他WIP保留，现阶段还不能验收“全固定板跑通”。


### 视觉固定跑法首次无伤联调（仍非全量验收）

新增atlas编译/固定动作程序/视觉跟踪与HybridAvoider，原arena_visual_runner通过小入口接线；随机板、无定位或动作预算不符继续原MPC。关级/地图/板序联合视觉识别来自背景ORB与原YOLO静态X锚点；无后台native状态输入。板内X连续外推累计不确定度，保留展开块序与loop visit，未知/重复假设冲突不强行定位。已确认身份允许短时独特图案立即定位，不再每次等待连续三帧导致错过仅一闪的入口特征；板序切换不能因同背景直接跳数板。像素atlas目录在打开时resolve，固定程序在按键ack后推进cursor，程序/图片特征文件SHA进入setup；源码SHA在原选板之前冻结。

50012联调：v3直接Unity取图去掉显示缓冲后进度偏差接近0，但定位未能起锁、两次受伤；v4改善连续性、222帧固定接管仍875伤；v5补入决策采样间隔/按键量化预算后只250伤，进度误差中位0.041m/P95 0.330m，仍一个错误身份帧。v6首帧stale_frame（未做动作，不能算无伤通过），v6b短组合仅时间约束仍500伤。最终v7短组合同时匹配原记录相对绳面的纵向姿态、原输入间隔和板内位置，**seed55200首次原arena实机整板无伤，11次固定按键**；v8默认入口、独立seed55201复测亦无伤，11次固定按键。两次均保留原初始段实时动作，不冒充每一键完全背板。v8实际验证区间识别278/291、错误身份0、动作区域定位237/237，进度误差中位0.036m/P95 0.153m/max0.350m；这是由100ms原生grader采样插值的估计，不是每帧精确真值。

显示捕获虽然request中位约3.6ms，但v2板内位置有约0.6–1m内容年龄偏差；直接取图request中位约12–13ms，却能保持位置一致。加载固定库时自动复用已存在RenderCapture（原Android按键运输不改），未配置库的入口仍旧路径；不增加用户菜单开关。快组合下翻参考原记录相对绳面高度，避免提前上翻后仍独立等待旧X导致落回较高位置；短时ack时钟同时受visit/相邻事件/空间/姿态限制，不是整板盲计时。

独立arena_fixed_validate仅在跑完后读取evaluation，记录原生/识别/实机三种不同证据。需原目标出口、无扣血、实际固定按键、正确身份和动作区≥95%定位及P95≤0.5m才通过；无特征初始空绳段不强制凭空产生绝对X，但身份覆盖仍按整板统计。vision_eval只增加只读stageStartX/instance与末关loop真实ID，loop出口要求新实例+起点前移；末关实机仍待。验证单放queue/validation，避免外部改写正在运行队列的内存coverage而丢结果。v8为首个detector/live验证通过场景，不能把全量native_passed写成视觉通过。

atlas-v5按当前原生队列和既有照片编译1052图/18场景，编译加入特征缓存与长板均匀抽样以保留出口，不只取头96图；现扩到更多场景复测。全量队列仍在50023，累计原生7/407（7种stage），343种固定布局中的其余仍未完成；50013内存失败保留，不能宣称全部固定板已跑通。当前13项固定策略/验收及合并50项相关视觉保护通过，原checkpoint 64项通过。旧飞竹/坡面等WIP不随本功能混交。

扩库后独立seed55202的v9仍500伤（142.858/180.169两处），未提升为稳定无伤。相同atlas-v5另外51013/51012/5001三板联调已开始；后续只累积事实，不以v7/v8覆盖失败。当前限制还包括未定位前的板序恢复、长时间无静态锚点、固定布局的动态状态差异；非单调/需要长时相位时钟的程序仍明确回退原MPC。


### 原静态布局匹配、跨板里程与中断恢复续记

扩库暴露背景软猜测被当成板子硬先验，导致一次空入口误猜后整板无法改正；现背景无绝对位置时只输出tentative，不锁定后续候选。静态布局从原CfgGameEnemyInfo的脚本/资源归类固定X蜘蛛和藏刃/爪子；Muppet、BT未知移动体不冒充静态锚点。固定repeat展开保留编辑坐标的空隙/重叠，7份原生resolved布局边界逐项差异<1e-10；无限段不编造成有限出口长度。YOLO静态排列可直接匹配整板声明，减少只靠稀疏参考照片造成的歧义。单条绳端只能在已有可靠进度下纠偏，不能从周期边界凭空建立绝对位置；先验超过180ms或不确定度超界失效。固定板真实长度通过视觉里程走完后，下一板独特视觉候选确认可传递板内里程，保留visit和误差，避免重新丢掉起点。

atlas-v6保留1052照片/18有图场景，50012加51个原静态X锚点；v7另加42份可识别静态声明，v8共有238场景元数据/213份绳边界声明。这些声明**不是238板原生通过、也不是238板实机通过**；覆盖分母仍343种布局/407场景。50022为EnemyHidePaw，已按原EnemyInfoHideBlade归类，不能只按资源名含HideBlade漏掉。源配置与展开回归、重复/移动体排除、照片缺少附近帧时的原布局定位、跨板里程、过期先验等保护合计38项相关测试通过。

实机失败完整保留：v10三板有两次首帧stale/51012有750伤；实际暂停帧预热后v11三板能完成但仍250/1250/750伤，不能说预热解决识别。v12纠正背景硬锁后50012部分接管仍750伤。v13 stale中止；v13b原静态布局匹配无伤；v14取图EOF后客户端桥无响应，没有完整报告，不计通过。只查arena自身日志/租约；原工具run-arena --restart --paused --no-focus完成恢复，并按既有入口重置超过阈值的进程命名空间。内核同期有NVIDIA分配失败，但尚无证据把它定为游戏退出的唯一原因。

恢复后v14b独立seed55202整板无伤、12次固定键，动作区241/241定位与正确身份、错误身份0，插值进度误差中位0.0445m/P95 0.3136m/max0.4113m。v15连续50012→50022→50031：第一板0伤、第二板700伤且没有固定接管。v16携带进度后第二板105帧固定接管，已识别成正确下一板；仍全程600伤（第一板250、第二板350），第二板定位161采样P95 0.571m，不验收无伤或稳定。所有记录保留原物理/碰撞/陷阱；下一步仍是稳定动作衔接与无静态敌人板的定位覆盖。

原生队列新增50023后累计8/407、8/343。53012在第31窗1200候选预算耗尽：前30窗472帧之前路径保持5000，但滚动rebase已经丢掉更早RAM节点，不能退回前几窗换跑法。不能用重开重放包装成回溯成功；需要真正保留较早快照。只读抽样宿主专属VM的3个RAM区域，每区2048页/8MiB，用本机liblz4原库压缩比例约0.371/0.376/0.382，仅为抽样、尚未实现压缩快照或跨窗口搜索。4节点none前缀缓存已离线验证轨迹等价且减少重复推进，默认仍0，未作原生性能承诺。

随后服务重启导致原控制台及worker退出，旧RAM点已丢失，未冒充原位续跑。核对进程不存在、私有socket连接ECONNREFUSED，并在arena-search控制租约内清理遗留socket；首次自动批处理因该socket拒绝启动的日志保留。新增arena_fixed_search_batch复用同一命名后端/原boot_client，交给mr3a-arena-fixed-search用户临时服务启动，避免聊天服务再次中断就终止整个搜索所有者；每个新案例初始化与训练撤销严格分开，撤销仍只用gate恢复。不按历史输入重放已完成案例；优先未尝试案例，失败/无参考案例仍留队列，未抹除。初始化拒绝新增原travel/state/board诊断，便于单点研究。全固定板目标仍未完成。


### 新证据自动编译与沙盒加载等待（服务重启续作）

新增arena_fixed_refresh持续读取原生通过证据，使用共享特征缓存编译新库，程序/atlas/摘要放入同一个版本目录后原子替换current符号链接。运行加载器只resolve一次bundle根，避免交叉读到两个发布版本；编译失败或编译期间原生证据变化不替换当前库，单实例refresh文件锁防止两个编译者冲突。新库仍标visual_execution_verified=false，不把原生出口当视觉无伤。mr3a-arena-fixed-refresh用户服务已实际发布首个8程序/1044照片/238场景声明包，原load入口离线加载成HybridAvoider通过；未将其写成全板实机验收。失败候选保留build.log，只有原生证据更新才再试，避免每30秒重复同一编译失败。

新入口诊断首次确认53052失败在Reset did not enter the battle：原角色已5000血/第20物理帧/x7.105，仍WaitGameStart，尚未到x8开局触发点，并非已到第五板后不安全。软件渲染的60秒加载期限过短。environment仅把加载等待改为可配置默认60，boot_client只在arena-search设300；原arena默认、20ms物理、陷阱、伤害和回退未改。受控SIGINT结束当时初始化并由原上下文清理VM后，启动mr3a-arena-fixed-search-v2加载新配置；此前失败仍保留，实际改善待新案例结果，不能提前记通过。56项相关视觉/静态/验收与65项checkpoint保护通过。原生8/407依旧；原先短窗前缀缓存默认关闭，真正跨窗口快照保留与回溯尚未实现。


### 真正保留跨窗历史与原客户端往返检查（11月18日上午续）

滚动rebase使53012的第31窗无法退回472帧以前，已新增独立、显式启用的`arena-file-ram`实验后端。原worker/默认内存形式不替换；`install_file_ram.py`仅给debug/arena-client下的私有Nyx checkout安装补丁和独立file worker/bench。每个完整VM快照的精确RAM页放入立即unlink的只读文件映射，CPU/KVM时钟/设备/COW磁盘仍沿用原快照；页缓存可回收，不靠从头重放、不手工恢复游戏字段。映射不是持久存档，所有者/worker死亡仍丢RAM点；没有实现压缩。修正Nyx原跨支深度断言误用active.depth的问题，新增不等深兄弟→保留未来→兄弟往返检查。

search的retain_history只允许该后端成功建立file-backed根后启用；保留每窗真实根，后窗有限预算无解时恢复前窗并排除其已提交输入前缀。区间40/60ms奇偶与已选路线长度一起回退，不重新初始化。废弃分支快照显式释放；已采图撤出发布清单并独立保留abandoned-references.json，图名使用单调序号防止覆盖失败证据。默认短窗none前缀缓存仍0。本搜索有窗口/候选预算，不是全局完备证明。

独立3GiB synthetic的100轮、110分支重复/不等深往返、三项时钟/计时器、原盘哈希检查通过；保存中位7.17/P95 15.45ms、同支恢复中位2.36/P95 3.46ms、跨支中位9.54/P95 13.04ms，范围仅测试虚拟机。随后原客户端`native-file-history-v1/audit.json`实际50012从22→577帧整板无伤：保存起点→完整搜索→恢复最早点→原生jump三tick新分支→恢复旧终点，起点和终点的全部已导出probe字段均相等、最终5000血。不是整个引擎的哈希，game_rollback_complete仍false；该容易板没有发生搜索死路后的跨窗换前缀。**冷的远距离原游戏恢复仍慢：最早点1677.31ms，另一分支的保留终点9037.76ms**，不能拿常规热恢复中位1.80/P95 5.29ms代替这两个慢尾。

随后两项宿主侧优化：映射页按文件物理顺序遍历；待恢复页先收集脏页及两支至共同祖先的差异，再沿目标链由新到旧批量解析，每页只写一次，避免逐页反复走长祖先链。仅Mapped后端使用批量路径，原Raw默认路径不改；`NYX_RAM_RESTORE=legacy`只用于同一测试二进制的对照。新的3GiB/100轮synthetic通过；另768MiB/180层、MemoryHigh1536M/MemoryMax3G对照均通过，跨支P95 21.52→16.53ms/最大33.34→22.19ms，同支P95 2.60→3.61ms，批量版有单次保存2058.86ms慢尾，尚不能说全面更快。256MiB夹具在启动就Shutdown，尚未进入回溯检查；209MiB initramfs可能占用过多启动内存，原因未单独证明，保留失败不当通过。详细在checkpoint-lab-deep-{legacy,batched}-v2/report.json；这组未覆盖原游戏9秒慢尾，仍待复测。

44项Python保护通过/1项跳过；FilePages两项Rust检查、file worker的COW父层生命周期检查通过，feature关闭的原worker/bench编译检查通过。原客户端/物理/陷阱源码无本次改动。原生累计11/407，343种布局其余仍未完成，视觉稳定无伤也未完成。mr3a-arena-file-history完成原生往返audit后卡在5306进场，SIGINT由所有者正常清理VM；当前`mr3a-arena-fixed-search-history`优先53012再继续队列，**正在用有序遍历的file worker，尚未换成批量解析版**；mr3a-arena-fixed-refresh继续自动编译新的原生通过证据。运行报告增加实际/proc/worker/exe SHA及能力标识，编辑器源码快照不能代替运行二进制版本；不要向持租约的VM另发命令。下一步看53012真正跨窗改前缀结果、原游戏批量恢复慢尾，再继续视觉动作衔接，不能用后台队列运行代替全部板已验收。


### 53012跨窗实测与有限窗视野修正（11月18日续）

有序file worker首轮53012在397帧后的候选触发严格步长检查：请求3tick、原advance实际走4tick，整板未通过。没有把4tick伪写成3tick；新增带完整job的NativeIntervalError，只将这种已经完成但边界不符的候选记为无效并整机restore，传输/源码/未完成错误仍中止。选中路线与route导出仍严格2/3tick。真实门接口的异常保留检查、无伤但越步的候选不能进路线等保护通过。

批量解析file worker的`native-file-history-v2/search/report.json`实际跑到53012第31窗472帧死路，1200候选预算耗尽后恢复前窗根457（961.763149ms），更换输入前缀，继续原客户端到472帧；这是原游戏实际跨窗回退，不是mock或重开。随后又走入相同未来，因为新的短窗只看到487帧左右、没有覆盖此前498帧失败，失败回退机制成立但搜索仍短视。该轮被受控SIGINT停止/释放VM，完整候选与报告保留；没有完成整板或新的起点/终点audit，不计第12个通过。

在保留模式的重试根上把前视增加一个commit窗，最高24区间；再次向更早根退时继续扩展，恢复向前推进后回到普通12区间。这样回退后会继续看见此前失败的未来，而不是只排除一个几乎无效的输入。保留模式另启最多4个none前缀的真快照缓存：复用已算过的分支节点、不再次执行同段物理，仍每次恢复真实整机快照/核对状态，默认滚动模式不变。40项相关Python保护通过。首次试验该组合为当前`mr3a-arena-file-history-v3`，目标53012、成功后继续队列；为了载入新的宿主搜索代码另起独立实验，旧v2 RAM点已失，不冒充原位续算或把启动当撤销。已保存实际worker二进制SHA；队列仍11/407。队列先处理尚未尝试的5/6级普通首板，再做需要原通灵兽进场的后段，所有失败仍留待队列，不抹除或计通过。


### 固定跑法姿态接口、通用方箱与短暂失位（11月18日续）

两处已查明的接口错误已修正：原一段跳名为jump:14，旧编译器只识别jump1，导致fall:15仍记0跳；现保留1跳直到原接触地面/绳子，二段跳前提为1。视觉jump1_rising/falling、jump2_rising/falling原被air分支排除，导致跳起后立刻交回MPC插入下翻；现与原air姿态及已用跳数一起匹配。高度/短组合时钟只能附加到空间触发条件，不能越过原输入的空间边界提前下翻。

定位失位后，在最多8秒内保留已由空间匹配确认的关级/地图/板序上下文，但过期绝对位置不再作为周期绳端的先验，未定位仍不执行普通固定动作。下一板可携带<=.97m的误差，> .5m仅作为未定位belief，需新的物理锚点纠偏才接管；修复一次画面在下一板确认分支中被confirm两次的问题。不要把这个上下文当成已确定新地图或板内位置。

当前标准20类YOLO的方形陷阱通常resource=None，旧匹配器等hideblade资源名，实际未使用爪子锚点。离线参考用原布局固定X对应检出方箱；实机只让3帧以上跟踪、与实测场景流水平速度相符的方箱提供候选，不把任意方箱认成静物或读取实机实体ID。缓存指纹含布局/局部X与特征函数；运行加载器核对feature SHA，不混用旧参考和新语义。该 coarse 类仍可能混淆，不当精确资源识别或完全无误。新11程序库已原子重编译。

已确认的自己jump1/2之后，短暂失位最多.5s、距下一录制动作>.1s且即时风险>.16s时可先保持当前原动作，避免MPC撤销已发跳跃；已确认输入的<=11tick相邻短组合，允许在同visit/真实当前姿态、位置误差<=.75m及原组合时钟窗口中完成第二键，不推进未确认的cursor。普通失位仍用原实时策略。另尝试用原flip风险模型回到未来录制稳定绳侧，前方不能有需执行的录制动作，风险必须为0；这只是复用原按键的接管衔接，不修改原绳子/碰撞/陷阱。

同seed55203连续50012→50022→50031的真实结果全部保留：

| 版本 | 第一板伤害 | 第二板伤害 | 第三板伤害 | 合计 |
| --- | ---: | ---: | ---: | ---: |
| v17 | 250 | 1575 | 0 | 1825 |
| v18 | 250 | 1400 | 0 | 1650 |
| v19 | 250 | 2581.25 | 0 | 2831.25 |
| v20 | 1250 | 1575 | 0 | 2825 |
| v21 | 0 | 1225 | 0 | 1225 |
| v22 | 1000 | 1050 | 0 | 2050 |
| v23 | 1000 | 1400 | 0 | 2400 |
| v24 | 750 | 700 | 0 | 1450 |

v21第二板169帧固定接管，v23的103→119m一段/二段跳保持原录制动作，中间6帧recovering；但各版本识别稳定度/受伤差异较大，不能从单次下降作因果或稳定无伤结论。测试与KVM搜索并行，截图/调度慢尾仍保留。33项固定识别/编译缓存/输入确认/状态恢复与批测保护通过；没有改YOLO权重或原advance/物理/陷阱，原arena每轮最终暂停菜单/输入/评估恢复。


### 原实时跑图器逐板批测队列

新增arena_fixed_live_batch只调现有arena_visual_runner，通过原arena InstanceSession独占控制，逐case固定原地图/板序/板子、三seed55200/55201/55202独立单板试跑。原生数据只在运行后交给arena_fixed_validate，不能进actor。记录按实际库/程序/源码/profile指纹和seed区分；已有graded或failed不反复空跑，库或源码改变再测，interrupted可重试。source bundle在开跑前后改变或被actor拒绝就不拿预期程序评分。超时先SIGINT给原runner恢复菜单/输入/评估，等待60秒后才回收失控子进程。与原生队列coverage内存状态分离，只写queue/validation及自身ledger，不能把native_passed写成视觉无伤。

32项固定相关保护及后来补充的参考缓存对应检查合计33通过；mr3a-arena-fixed-live已启动。首两个51012、51013原实机均passed_with_damage，detector/live均False，正确保留为失败；其它逐板仍在进行。入口服务启动命令见systemd用户临时单元；结果在debug/arena-client/fixed-route-work/live-batch/ledger.json和runs，后续原生新通过经mr3a-arena-fixed-refresh原子编库后自动加入。范围只是单板入口，不能代替连续跨板或全部竞技场无伤；三板联调失败表仍有效。


### 往起跳前回退与继续实机定位（11月18日中午续）

v3再次在53012第31窗耗尽1200候选，真实回前窗980.58ms，已开始18区间前视的重试，未完成整板。进一步核对既有原生路线：382帧/134.55m/3.25高仍runOnGround；397帧已掉出平台，第一次跳拖到427帧、y=-5.42；457帧y=-5.59才二段跳，472帧y=-3.92且两段已用完。故只退457帧会在已经失去操作空间的空中重复枚举。保留模式现优先回到最近原生runOnLine/runOnLineDown/runOnGround/slideOnGround根，跳过中间空中根，所有撤回窗/参考图/节点同步清理，扩大前视最多24区间。仍为有限搜索启发，不是不可达的数学证明。延期死亡假oracle已验证一次跳过多个空中窗、恢复起跳前真根再改变输入，40项相关保护通过。

当前加载该策略的是mr3a-arena-file-history-v4（旧v3受控结束/点已失），search/report.json保留backtrack_policy、skipped_attempts与实际worker SHA；原客户端实测仍在进行，未把新启发记为通过。audit入口现在也通过同一WorkQueue登记active/attempts/初始化诊断/完成或中断，避免现场明明在53012而coverage仍显示旧53061；即使有限搜索未到出口，也可做字段往返审核，但只有原出口无伤才进入native_passed。

实机匹配另修正一个过硬的排除条件：多出参考图没有的动态类别，不能否定已由静态几何独立对齐的候选；只有无几何证据的纯背景候选继续硬排除，几何候选仍受语义不一致的置信惩罚。新增包含新动态类而3静态锚点一致/无几何仍拒绝的保护，固定相关34项通过。实机新版本成绩待队列。

mr3a-arena-fixed-live-v2现续同一live-batch ledger；旧live服务SIGINT正常退出。指纹只跟踪actor入口及其静态导入的arena模块和profile/库，单改独立checkpoint实验不会再把整批视觉成绩作废重跑。首轮51042、50031有单板0伤，但识别/实际固定接管没有达到验收，仍False；其它已测有伤，未虚报为固定板完全跑通。原生计数仍11/407，原生、单板视觉与连续跨板验收分开保留。


### 真实恢复超时、进程回收与daemon重启续作

v4在第29窗、尚未触发回起跳前策略时，restore请求超过20秒；随后重复恢复/关闭同样等待超时，强杀等待5秒也超时，最终worker退出但遗留拒绝连接的socket。完整栈在mr3a-arena-file-history-v4 journal；search/report.json保留TimeoutError及28个已提交窗。不是已验证的内存压力原因，也没有Rust panic证明；不能因提高deadline就称根因修复。旧RAM点已丢失，该轮未新增原生通过。

文件后端现在单个restore socket等待180秒，Raw后端保持20秒，仍读取同一请求的原结果；增加NYX_TRACE_RESTORE可选宿主分阶段日志（脏页/祖先/目标页/base/CPU/block/VM时钟/TSC），不改变游戏状态/物理或恢复结果。叠加trace后的3GiB独立VM30轮、原盘/时钟/计时器检查通过（checkpoint-lab-trace-v1），只属synthetic。私有安装器支持补丁栈逆序剥离再重放，重入结果一致，拒绝未知更改时恢复输入；真实三文件夹具核对在installer-stack-fixture-v1/audit.json。

实例后端缓存worker能力，强杀后最多等30秒确认结束；仅在确认退出后清理socket。新增worker-owner.json记录PID及/proc启动时间，在同一InstanceSession租约内，只有旧进程确认已死且socket拒绝连接才自动清理，PID仍活或有listener均拒绝，不杀其它控制者。46项保护通过，含慢退出/原异常保留/活listener拒绝/单个restore请求等待。第一次无owner文件的旧socket已在独占租约中核对无worker、ECONNREFUSED后手动移除。

当前原生服务是mr3a-arena-fixed-search-v5：原有batch入口/file worker、恢复追踪开启、MemoryHigh回到曾通过原生audit的14G；Restart=on-failure/15秒，异常新epoch不冒充原RAM续算，更不作为搜索撤销。原生还是11/407，改先处理其它未尝试固定场景，53012失败仍在队列。daemon重启后已核对本服务/worker及mr3a-arena-fixed-refresh、mr3a-arena-fixed-live-v2均保留运行，没有重复启动。

视觉ledger累计54项graded、1项interrupted、1项failed（包括旧/新actor版本，不能当54种板子）；50012 seed55201有一项识别/进度/实际固定接管/无伤全部通过，其它场景未联合通过。空板50031及51042虽有0伤，仍因识别/接管不达标为False。实测服务已完成现有库的这一轮并等待新库/actor版本，不反复空跑已判失败；原生新证据仍会自动编库→加入原视觉验收。所有固定板无伤与连续竞技场无伤均未完成。


最后补充：socket真的超时后，新的实例所有者会把该epoch标为传输状态未知，禁止再追加restore/state等命令，转进程清理；真实Unix socket测试证明只发送一次restore。该补充在当前v5进程启动后写入，需下次所有者启动才加载，当前进程已有180秒等待和分阶段追踪，不为加载该补充丢掉现有RAM点。Raw两二进制feature关闭的编译检查仍通过。

逐场景三seed汇总已写live-batch/triage.json：51012/51013/51043/5001/50023多轮没有固定键；51042、51073、50022还出现米级到42m的进度误差，53011有错身份。首先补了重复排列歧义保护：原静态布局仍允许另一个发生位置时，较好看的照片分数不能覆盖这个结构性竞争解释；必须有新鲜空间先验才选定出现次数。35项固定相关保护通过，新实测自动排队，不能当作42m错误已实机修复。其它问题继续按该汇总单点排查。


恢复队列又补了epoch故障传播：transport已未知或worker已退出时直接让所有者失败退出，交给受控重启，不把后面尚未尝试的案例也逐个标成失败。正常原生进场失败仍保留原来的单案例处理。47项保护通过；同样在下次所有者启动生效，不为宿主保护小改动抛弃当前有效RAM点。v5当前已正常进入5301、保持5000血继续有限搜索，分阶段日志均完成，超20秒故障尚未复现；这不等于根因已修复或5301已通过。


### 继续：用原生早跳分支改善短窗末态

v5搜索5301实际两次跳过4个窗回到原地面根（2.602/2.053秒），回退正确但改出的晚跳仍陷入深处；37窗后还没有出口，受控结束并保留interrupted报告，未记通过。此前常规候选restore最大478.51ms，未重现v4的>20秒异常；仍不能据此断言根因已解决。

问题是只按输入数找短窗可存活的第一条路，会让角色先掉到平台下很远，再到死亡前一刻才跳。保留模式新增一次原引擎rollout提示：root为原fallFromRun且当前完整候选末态已比root低超过两个原生Role碰撞箱身高时，先试root立即跳、后面保留正常候选搜索；只有原引擎整段无伤且末态更高（至少半身高）或已出口，才优先取这条。原候选保留，早跳受伤或预算耗尽就回原候选。覆盖无操作候选及已经含晚跳的候选，均不改原物理/陷阱/HP；仅file-backed保留模式启用，原Rolling默认不变。这是有限窗的搜索优先级，不是用自写物理判断安全。51项保护通过，包含早跳受伤/预算不足回原候选、深处晚跳改早跳、真实节点恢复和废弃参考撤回。

为了加载新的宿主搜索器，v5及尚在启动的v6已由各自所有者SIGINT收尾，旧RAM点不冒充续存；当前mr3a-arena-fixed-search-v7对同一5301开始独立实验（--case L5-M43-S1-B5301），之后续全队列。搜索撤销仍只用真VM点，不重开重放；此时早跳提示原客户端效果待验，原生仍11/407。mr3a-arena-fixed-live-v2最近50012 seed55202也有联合验收True，但要按actor版本/seed看ledger，不能与旧成功混成全库完成。
