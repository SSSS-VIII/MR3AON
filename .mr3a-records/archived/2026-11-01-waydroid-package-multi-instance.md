# 包管理器版 Waydroid 双实例落地

## 现象 / 需求

用户明确继续使用 Waydroid，且当前安装来自包管理器，不能要求换成其它 Android 容器或另构建一套 MR3A。先解决两个独立 Android 窗口同时运行，为后续脚本多实例隔离提供基础。

## 原因

本机 RPM `waydroid-1.6.3-1.fc44.noarch` 的 Python 管理层硬编码默认工作目录、Binder、D-Bus 和网桥。未合并上游 PR 的网络部分仍会共用 nftables 表，直接复制工作目录或调用两次 show-full-ui 无法隔离。默认 ADB server 暴露两台设备还会使现有 MR3A 的单设备检查失败。

## 改动

- 新增 `tools/waydroid-instance` / `tools/waydroid_instance.py`：通过进程内 source loader 读取已安装 `/usr/lib/waydroid` 的代码，只对当前进程替换实例目录、服务名、Binderfs 和 DHCP 租约文件引用。不修改 RPM 文件，不编译、不复制整套 Waydroid/MR3A 源码。
- 当前适配限定 Waydroid 1.6.3；包版本变化时拒绝直接套用。`--slot 1..14` 映射独立资源；实际验证的是主实例加 slot 1，不能推定已验证 14 开。
- 共享 `/var/lib/waydroid/images` 的只读镜像；实例单独持有 rootfs 挂载、overlay upper/work、配置和 Android userdata。主环境 ARM 转译 overlay 用 reflink 快照继承，不复制账号数据；次实例禁止镜像下载/替换。
- 每个 slot 独立 D-Bus policy、会话名、Binder 节点、桥、子网和 nftables 表。次实例不使用原管理层按进程名终止全体 sensord 的逻辑，也不操作主机 NFC、剪贴板和通知。桌面文件写在实例自己的 XDG data 目录。
- 启动系统/用户 transient unit 管理次容器与会话。等待会话 D-Bus 对象就绪后再 show-full-ui，修复冷启动时 show-full-ui 抢先自建另一会话的竞态；创建独立用户状态目录，避免第二次启动的迁移标记缺目录错误。
- 每个 slot 独立 ADB server（slot 1 为 5038），共用系统 adb 可执行文件；主 server 5037 保持只连接主 Android。使用 `tcp:5038` 的本地 socket 格式，使 adb 可自动启动 server，实际监听仅 127.0.0.1。
- `authorize-adb` 将调用 sudo 的用户的**公钥**追加到次 Android 的授权列表，不读取私钥、不改主 Android 授权；重复执行保留已有授权。设备授权和分辨率已在 slot 1 完成。
- 驱动准备后重新生成次实例 LXC 设备配置，避免主机重启后 Binder major/minor 变化导致旧 allow-list 失效。host reboot 尚未实测；命令均为按需启动，不注册主机开机自动双开。

## 本机落地

- 次实例系统状态：`/var/lib/waydroid-mr3a1/`，日志 `waydroid.log`，独立生成网络配置脚本。
- 用户数据：`~/.local/share/waydroid-mr3a1/android-data/`；用户侧状态/桌面文件在同级实例目录。
- 网桥 `wdmr3a1`、子网 `192.168.241.0/24`，当前设备 `192.168.241.112:5555`；地址由该实例 DHCP 分配，应以 status 为准。
- Binderfs `/dev/binderfs-mr3a1`，只把带 `-mr3a1` 的设备链接发布到 `/dev`。
- D-Bus：`id.waydro.Container.mr3a1` / `id.waydro.Session.mr3a1`；新增 policy `/etc/dbus-1/system.d/id.waydro.Container.mr3a1.conf`。
- 服务：`mr3a-waydroid-1.service`（系统）、`mr3a-waydroid-session-1.service`（用户），由工具创建 transient units；主 `waydroid-container.service` 保持原样。

## 验证

- 新增 8 项测试通过：slot 资源不重复、非法编号拒绝、D-Bus 名称与接口隔离、网络 start/stop 不使用主 nft 表、CLI help 无需加载系统实现。Python 编译和 Bash 语法通过。
- 两个 Waydroid 窗口同时存在；两个 Android 的 `sys.boot_completed=1`、Android ID 不同。主服务 PID 和主窗口进程在测试前后不变。
- 次 Android 创建的探针文件在主 Android 不存在；次实例停止、重启后文件仍保留，验证完已删除探针。次实例分辨率设置为 1280x720。
- 主 ADB server 5037 只列出 `192.168.240.112:5555`；次 server 5038 只列出 `192.168.241.112:5555`，两者均为 device。次实例网关及公网 IP ping 成功。
- 停止和重启次实例后，主 Android boot_id、主服务 MainPID 与主 `inet lxc` nftables 表均与基线一致。未启动/重启主游戏。
- `rpm -V waydroid` 无输出，确认包管理器安装的文件没有被改写。
- 保留两个窗口供用户查看。MR3A 的运行目录、配置、奖励图和退出逻辑尚需下一功能接入；不能将本次 Waydroid 双开等同于脚本隔离已经完成。
