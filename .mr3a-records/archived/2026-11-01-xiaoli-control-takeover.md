# 小鲤通过受限工具停止脚本并接管实例

## 需求

实例被脚本占据控制锁后，小鲤的受限设备工具无法操作，也没有宿主进程管理权限。用户要求给出显式接管能力，停止正在控制 xiaoli 的脚本。

## 原因

原 control 只有非阻塞排他租约，冲突即报错；设备 stop 又要取得同一租约才能关闭 Android，无法用它停止占用者。受限工具不应该通过宿主 shell、任意 PID 或其它实例参数解决该问题。

## 改动

- `InstanceSession.control(takeover=True, timeout=10)` 可显式停止当前锁持有脚本后取得原锁；默认 control 保持拒绝冲突，不自动接管。
- 根据 `/proc/locks` 中 FLOCK 的设备号/inode 找实际持有进程；打开 pidfd 后再核对内核锁归属和进程用户，不信任可过期 PID 文件，不通过删除/重建锁文件制造双重控制权。
- MaaPiCli 先请求 SIGUSR1 正常停任务，一般控制脚本先 SIGTERM。超时才升级终止，并清理已验证的原进程树子进程，避免继承锁或残留输入进程。只使用固定 pidfd，不按进程名批量停止或杀整个宿主会话。
- 如果原进程树还持有其它 MR3A 实例租约则拒绝停止；若停止后有新请求先拿到锁，本次报错而不继续终止新控制者。等待限为 1–30 秒。
- 小鲤的 `game_control` 和固定 controller 增加 `takeover` 操作，工具定义含使用说明、有限超时及单次租约边界。它始终创建 xiaoli 会话，调用者不能选择 name/PID/端口。接管不关闭 Android，不启动离线设备，不重放游戏输入。
- 原 stop 仍为关闭 Android；接管成功后先 screenshot/read_image 再操作，返回后释放单次租约。小鲤 README、takeover.md 和 GUIDE.md 补充接管用法；私有运行指南只追加同一段落，保留已有学习内容。配套代码/测试/文档提交为小鲤仓库 `67a15a4`。

## 验证

- 29 项命名实例/路径/接管保护测试通过；包含真实宿主子进程持锁、只停止 xiaoli 且 main 存活、同时持有多实例时拒绝、忽略 SIGTERM 的脚本和继承锁子进程最终回收、锁归属变动时不发信号、普通操作不自动接管。
- 小鲤 Python 控制器 15 项、独立插件 Node 3 项测试通过；覆盖 action schema 可发现/调用、忽略外部实例名和 PID、超时边界、不启动或关闭 Android。
- 通过真实固定受限入口 `game/control --json` 调用 takeover 成功。此前占 xiaoli 锁的 Python 脚本 PID 2556580 已退出，status 返回 android_running=true、control_available=true，随后同一入口截图返回 1280×720。main 的既有 MaaPiCli PID 2037051 仍运行，未受影响。
- 普通全量回归：137 passed、5 skipped、5 failed、80 subtests passed；失败仍为既有悬赏路径/旧节点和 enable 双字段断言，不修改旧断言掩盖。
- 两个仓库 diff 空白检查及 Python 编译检查通过；没有在游戏里新增点击，没有修改账号配置。
- 已重启用户服务 qqbot.service 以重载独立游戏插件，状态 active/running，MainPID=2626606；既有主会话配置/ID未修改，没有发送聊天测试消息或制造新模型轮次。主环境脚本 PID 2037051 重载后仍在运行。受限工具仍使用原 game_control 名称及固定 xiaoli 控制器，新增 action 无需宿主命令白名单。
