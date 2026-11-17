# 独立整机回溯实验

包含合成夹具和后续原 Android 客户端沙盒。原客户端已通过一次真实受伤回退和同点重复分支检查；**跨板、死亡和长期运行的完整验收仍在继续**。合成结果与游戏结果分别记录，不混为同一结论。不使用外部 ADB、不修改宿主内核/网络、不更换现有 arena，也不加载到用户菜单。

## 原客户端实验后端

只接受 `InstanceSession('arena-search')`，使用既有同名控制租约。私有配置/磁盘在 `.mr3a-instances/arena-search/checkpoint/`；单 vCPU、3GiB、无 NIC，Binder/Weston headless/ANGLE 软件渲染全部在客体内。APK与白名单资源来自原arena，不复制账号。`android_prepare.py`拒绝覆盖已经准备的实例；`android_payload.py`显式只读复制资源。研究依赖/本机环境及第一次准备过程见专题记录，不要对现有Waydroid磁盘运行这些安装操作。

初次安装只能在显式 `provision` 阶段让**这个名字自己的 userdata**使用Sync；worker此时禁止snapshot/restore/rebase。安装与sync完成后停机，通过持租约的`set_phase(session,'checkpoint')`切全部Cow，再启动。不可对直接写盘客体做回溯。

已有准备好的私有镜像时，先将`worker.rs`复制为固定研究克隆的`src/arena_checkpoint_worker.rs`，使用下文的编译环境构建`arena_checkpoint_worker`。启动内部控制台：

```bash
PYTHONPATH=agent .venv/bin/python -u tools/arena_checkpoint_console.py
```

控制台中 `gate=start_client()` 会编译两个约10KiB的JNI桥和小型DEX，完成原GameOnly冷初始化，再移交给Unity主线程gate。使用Android userdebug原有`am attach-agent`调用原UnitySendMessage；没有Frida、JVMTI hook、APK重签名、陷阱替换或自写运动更新。JNI头来自固定SHA的AOSP，编译工具复用本机已下载的ecj/D8/Android SDK。该冷初始化**不是回溯**，后续搜索不能重启它来重放历史。

```python
point = gate.snapshot()
step = gate.step(3, 'none')  # 原20ms tick，共60ms
gate.restore(point['result']['id'])
step = gate.step(3, 'down')
native = gate.call('probe') # 有限原生字段观察，不能称为完整引擎hash
```

50ms采样交替使用2/3原tick。`gate.view`是已经停住的主线程结果，读取它不推进客体；重复state/probe也不增加Unity帧。game gate接管后禁止旧`sh`/文件RPC，且只能恢复本gate创建的点，因为宿主选中的mailbox地址/CR3不属于guest快照内容。带GATE code的响应与可能迟到的root响应分开检查。操作超时后禁止覆盖命令或保存伪停点，只能恢复已知gate点。

`lifecycle.run_boundary(gate, output)`从出口前停车点验证跨板及敌人ID生成/退出，逐段恢复对照并检查PNG；`lifecycle.run_native_death`检查原Die入口后恢复与替代动作，不代表自然致死/完整结算验收。原Die会把时间倍率改为.5，受控检查需在返回后停回0；任意exec若破坏暂停条件可能使门控超时，此时恢复已知gate快照，禁止覆盖未完成命令。

`search.run(gate, output)`是独立的原引擎oracle有限窗DFS，默认12个40/60ms交替区间，确认前6个再rebase；每个候选实际运行原输入，扣血即恢复VM父节点，找不到窗口内解/预算耗尽明确失败并留下根点。重建RAM基线会放弃更早历史，因此这不是全局完备搜索；不允许用重开/历史输入重放兜底。`trials.jsonl`保留所有成功/失败候选，`report.json`只把真正提交的无扣血动作写入route；起止原地图/板序/坐标/帧/绳上绳下状态明确记录。它不读取YOLO、不修改陷阱，也尚未接视觉执行器。初始化原选板可单独使用一次，不能放入撤销路径。

窗口内按非none输入次数0/1/2…迭代，优先找到较早的一次跳跃，而不是先耗尽大量晚动作组合；同一真实点已实测受伤的动作可跳过。仍有全局候选上限，无法保证所有局面更快。开跑时冻结实际已加载搜索源码及依赖，编辑源码不覆盖正在跑的版本证据。

`route.export([report_paths...], destination)`校验每个提交区间、逐字段接缝及原生板出口，导出板内坐标动作；相邻报告必须确实停在同一原state/板上下文。首条`native-route-50012-v2.json`为42→577帧保持5000血进入50022；起点之前和视觉部署均未验收。完整失败候选流留在各自`trials.jsonl`。报告源文件在运行中可能更新，SHA可检测变化；已导出标准记录不要覆盖。

原生选板可能重新把Unity设为1920×1080。搜索入口通过`render.prepare`再次请求320×180，每个确认窗口检查实际尺寸及renderFrameInterval1；只有16:9允许此路径，不跳渲染帧。60tick原生动作/藏刃/蜘蛛对照一致，36.7→7.36s。`render.verify`用于从高分辨率停点复验；普通arena与视觉截图分辨率不变。

`gate.rebase()`在当前停点生成新的完整RAM根并释放旧RAM祖先，旧点ID全部失效；不重开游戏、不重放动作，也不重写角色字段。该操作要额外暂存一份3GiB RAM，有空闲内存保护；已有实际分支一致性、磁盘读写和PNG恢复检查；跨板/死亡/长期增长仍待验证。COW盘父层是Weak引用，worker会独立保留磁盘层强引用；其历史缓存长期增长仍待测量，不能把RAM树释放等同于全部内存有界。控制台退出会关闭自有VM；目前RAM快照不跨进程持久化。

首例证据为`native-game-gate-v1/report.json`：map42/stage50012，第136→139帧原碰撞5000→4750，整机恢复73.89ms后改下翻保持5000；同点四次完整已导出字段一致。`game_rollback_complete=false`仍保留，不能把单例当完整生命周期通过。v4的11项有限检查已全部通过，含修正COW父层后的RAM新基线与PNG字节一致；受伤恢复48.43ms。当前软件渲染搜索较慢，step和restore分别计时。v1实验JSON为游戏原json.stringify格式；后续gate源码沿用既有文件桥的17位数值/数组编码，需按冻结源码区分证据版本。

## 合成夹具

快照使用 Nyx-Lite 的基础 RAM + 脏页增量树，保存客体 CPU、内核、设备和 COW 磁盘。只读已有基础磁盘；没有宿主 GPU、显示/网络服务透传。线程、TLS、栈/堆、mmap/munmap、子进程、未读取的 Unix socket 消息、文件 FD/偏移与 fsync 都在客体内。64MiB 映射逐字节参与 hash，同一快照反复执行同操作应得到相同状态，不同操作应形成不同分支。

可额外验证客体 Binder 设备创建/协议/context manager/持有 FD，以及 llvmpipe 的 EGL pbuffer、清屏/裁剪和像素 hash。另在基础/中段/末段快照检查单调时钟和待触发 timerfd，主动等待50ms宿主时间后恢复，核验计时误差及提前过期。**这不等于 Android 服务通信或 Unity 渲染全部通过**；没有测试 GPU 透传、复杂 shader/纹理/动画、Android Framework、游戏伤害和对象生命周期。KVM 时钟仍有执行抖动，需要在实际客户端继续核对。

## 本机已使用的依赖

- Nyx-Lite `489fd4d27e05bd3ccac7804173a22d8ea6789839`。
- Firecracker 子模块 `eacf499b0badf7fe4aaefe8d30237db439018319`，未改该子模块。Nyx-Lite 外层有下述局部时钟补丁。
- 本地克隆在 `debug/arena-client/rewind-research-v1/nyx-lite/`；不入库。
- 旧 AWS-LC 依赖与本机 GCC/CMake 不兼容，研究克隆里 `cargo update -p aws-lc-rs --precise 1.19.0`；最终 Cargo.lock 随结果封存。最终编译环境为 `AWS_LC_SYS_CMAKE_BUILDER=0 CC=clang CXX=clang++`，不修改系统工具链。
- 普通实验使用 Firecracker 的 ELF `vmlinux-6.1.58`。Binder 实验使用本机 Fedora 内核的**解压副本**和匹配的 virtio_mmio 模块；没有安装、切换或重启宿主内核。

## 准备与运行

先在上述固定版本 Nyx-Lite 克隆中应用本目录的 `nyx-rewind-clock.patch`。它只改独立实验后端：在 RAM 复制前获取时钟/CPU/设备状态；保存结束恢复该时刻；恢复时另设 flags=0 的 KVM clock，避免迁移接口添加宿主流逝时间。未修改版实测曾产生约1.3秒的基础快照时钟误差，不能只看内存 hash 宣称成功。该补丁没有加载到原客户端或运行实例。

补丁以零行上下文封存，针对上述精确版本，应用命令为 `git apply --unidiff-zero /home/linn/MR3A/tools/arena_checkpoint_lab/nyx-rewind-clock.patch`。

从仓库根执行，输出目录必须全新。先准备完再编译，不能并行这两步。

```bash
python tools/arena_checkpoint_lab/prepare.py \
  --nyx-root debug/arena-client/rewind-research-v1/nyx-lite \
  --kernel debug/arena-client/rewind-research-v1/nyx-lite/vm_image/vmlinux-6.1.58 \
  --output debug/arena-client/rewind-research-v1/my-checkpoint-lab \
  --mem-mib 3072
```

然后在 Nyx-Lite 克隆目录编译：

```bash
AWS_LC_SYS_CMAKE_BUILDER=0 CC=clang CXX=clang++ \
  cargo build --release --bin arena_snapshot_bench
```

回到仓库根运行：

```bash
python tools/arena_checkpoint_lab/run.py \
  --binary debug/arena-client/rewind-research-v1/nyx-lite/target/release/arena_snapshot_bench \
  --output debug/arena-client/rewind-research-v1/my-checkpoint-lab \
  --rounds 1000
```

Binder/软件 GL 组合在准备时附加 `--android-primitives --software-gl --initrd --virtio-module <匹配客体内核的virtio_mmio.ko.xz>`，并选择 Binder-capable ELF kernel。`--clocksource tsc` 与 `--clocksource kvm-clock` 可分别核验两种客体时钟。不要把宿主设备节点或正在运行的 Android 磁盘放进配置。软件 GL 依赖本机 Mesa 开发头文件与动态库，构建时只复制相应库至私有 rootfs。

每次输出含冻结源码、Cargo.lock、Nyx 核心补丁、guest/内核/基础磁盘/benchmark 摘要、配置、原始日志和 report。report 保留失败和超时；即使日志出现 pass，非零退出、基础磁盘改变或能力不符也不能通过。`game_rollback_complete` 始终为 false。

`base_save` 是一次性的全 RAM 基础快照；后续保存只复制脏页。恢复数据分为同一节点重试和跨分支跳转，均包含 CPU/设备恢复。合成 guest 执行、64MiB 全量 hash 和 fsync 的耗时单列，不算进恢复延迟。夹具没有把50ms游戏逻辑接入，因此这些数字不证明游戏已能回到50ms前。

具体实验结果与客户端接入约束见 [开发记录](../../docs/records/archived/2026-11-17-arena-fast-checkpoint.md)。
