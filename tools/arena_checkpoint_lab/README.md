# 独立增量快照实验

这是合成 Linux 客体的底层验证，**没有接入 Android 或竞技场客户端**。不把结果当作游戏回溯验收。它不使用 ADB、不修改宿主内核/网络、不更换 arena 的后端，也不加载到游戏菜单。

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
