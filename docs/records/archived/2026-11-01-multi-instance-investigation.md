# Waydroid 多实例与脚本运行隔离：需求和可行性调查

## 现象 / 需求

用户希望同一份 MR3A 源码、Python 环境和 MaaPiCli 可执行文件支持多个同时运行的 Waydroid 窗口。各实例独立绑定 ADB，隔离 PiCli 配置、Agent 持久化状态、debug、日志、奖励截图及其它运行写入。不要再为测试复制可执行文件或整套项目目录；正常测试沿用主环境，必要差异仅在配置与运行数据。

用户尚未创建第二个 Waydroid，需要本次连 Android 双开环境一起考虑。鬼族仍暂缓开发，已有工作不纳入本任务提交。

## 已确认的原因与约束

- 本机 Waydroid 为 1.6.3，CLI 没有实例参数；系统 D-Bus 容器名、用户 D-Bus 会话名、默认工作目录和网桥均按单实例设计。不能将两次 `show-full-ui` 当作两个隔离 Android，也不能只切换用户数据却声称同时双开。
- 上游多实例需求 [#566](https://github.com/waydroid/waydroid/issues/566) 与实现 [PR #1990](https://github.com/waydroid/waydroid/pull/1990) 在本次查询时仍开放。PR 修改容器工作目录、Binder、D-Bus、网络和用户数据，尚有 Binder 与 nftables 名称冲突反馈，不能直接宣称在本机可用。
- 本机主容器正在运行；已有 192.168.240.0/24 网桥、共享 Binder 节点和 Waydroid 服务。部署次实例前须验证独立 Binder/网桥/规则/服务名，不能让次实例的停止或恢复命令作用于主实例。
- `adb_target()` 当前要求设备列表恰好一个可用设备。多实例必须按配置显式选择 serial，设备缺失时不得回退到另一台可用设备。
- MaaPiCli `source/MaaPiCli/CLI/main.cpp` 将用户目录和资源目录都取自 `library_dir()`。只改 cwd 或建立二进制软链接不能保证 PiCli 配置和框架日志隔离；需要给同一可执行文件提供独立目录参数。
- Agent 在导入 logger 时已创建日志目录，开发模式又切 cwd 到 `assets`；`MR3A_TEST_WORK` 只覆盖部分路径。奖励图、deadline 截图、元数据缓存和老板娘学题写入均需纳入统一运行路径，不能把可写 data 软链接回共享源码资源。
- TUI 退出目前按祖先/会话/TTY 查找 PiCli；进程清理也须检查实例归属，避免退出一个实例影响另一个。

## 方案边界与当前状态

- 共享：MaaPiCli、动态库、Agent 源码、虚拟环境、流水线、图片和 OCR 模型。
- 独立：Android 数据、Binder/容器/会话/网络、ADB 目标、PiCli/Agent 配置与状态、日志、debug、奖励、可写缓存和学习数据。
- 实例目录只放配置与运行数据；不用「再复制一套 MR3A」实现隔离。默认主实例继续支持，现有 run-test 的机制需要按用户新需求重新设计，不机械沿用旧约定。
- 待用户明确实验性 Waydroid 补丁路线、先完成脚本隔离或研究其它多实例 Android 容器的偏好。选择前不替换系统 Waydroid、不应用网络规则、不启动或停止任何现有实例。
- 本轮仅完成调查和需求归档，尚无多实例实现或双开验证；后续按 Android 双开、脚本运行隔离等功能分别开发、验证和提交。

## 验证

- 阅读相关工作记录、MR3A 及本地定制 MaaPiCli 历史/代码；只读检查已安装 Waydroid CLI、源代码、服务、Binder、路由及本机资源。
- 下载 PR diff 到 `/tmp/mr3a-waydroid-multi-instance-1990.patch` 供审查，未应用。核对最新评论中的网络规则冲突反馈。
- 未修改业务代码、PiCli 配置、Android 数据或系统服务；未进行游戏/双开实测。调查本身没有新增业务测试。
