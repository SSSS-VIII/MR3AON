# 小鲤通过原 run 执行启动游戏，再交还设备

## 需求与原因

用户明确游戏是小鲤自己的独立能力，QQ 只是通信软件。上一版外部入口直接 am start，没有使用 MR3A 的启动游戏任务；小鲤配置仍为空，也没有设置渠道/区服；常驻控制器持续持有租约，阻挡原 run。这不符合要求。

## 改动

- 外部 `~/xiaoli/run` 现在只执行本项目 `run xiaoli --task 启动游戏`，不接受额外任务参数，不管理环境或后台服务。
- 已为 `.mr3a-instances/xiaoli/config/maa_pi_config.json` 写入唯一「启动游戏」任务：渠道 `oppo`，区服 `上次登录`。用户明确选择保留上次区服，未强制改为五区。密码留空，不复制 main 凭据。
- 小鲤 `maa_option.json` 使用 logging=true、save_on_error=true、stdout_level=0，关闭框架截图探测失败时的 PNG 二进制终端噪声；共享源码和 main 配置未改。
- 游戏能力已移到小鲤仓库中的独立 DSH 插件 `@xiaoli/dsh-game`，工具 `game_control`，设备入口 `~/xiaoli/game/control`。移除旧常驻服务及 QQ 游戏实现；设备操作只在单次请求内取得租约，不调用 ensure_ready，自身不启动 Android。生命周期和恢复仍经 MR3A 原 run。
- 本轮 MR3A 仓库只更新文档与记录；游戏实现、模板及测试在小鲤仓库，运行配置不入 Git。原有鬼族暂存内容保留。

## 验证与边界

实际从 `~/xiaoli/run` 启动，共用 MaaPiCli 日志确认 `count=1, entries=['启动游戏entry']`；实际包名 `com.pandadastudio.ninjamustdie3.nearme.gamecenter`，override_nodes 包含 `启动应用`、`跳过切换区`、`输入登录密码`。设备进入 OPPO 账号登录页，账号尚未提供，没有继续填写或登录。通过本次 MaaPiCli 的 SIGUSR1 正常停止验证，Android 保留，随后独立控制器取得控制权并读取 1280×720 截图。

尚未验证账号登录后整项启动任务自然完成，不能把本次停止后的退出码 0 写成成功进入游戏。MR3A 已有队列结束退出逻辑，本轮没有改动它；现有启动任务包含登录与启动收尾流程，并非仅打开应用。账号信息由用户后续补充。

小鲤控制器 12 项 Python 测试、独立插件 3 项 Node 测试通过；QQ 桥 793 项回归通过。独立插件注册测试不需要 QQ 会话。源码约束、入口参数、渠道/区服模板均有检查。
