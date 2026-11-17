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
