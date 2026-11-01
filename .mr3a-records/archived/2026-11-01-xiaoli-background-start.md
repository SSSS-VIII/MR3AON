# 小鲤启动游戏不打开桌面窗口

## 需求与原因

用户希望小鲤启动游戏时只准备后台 Android，不拉起桌面窗口。原 `InstanceSession.ensure_ready()` 调用底层 start，后者在会话就绪后无条件执行 show-full-ui，导致每次启动都会显示窗口。

## 改动

- 命名入口和底层 start 增加 `--no-window`，默认行为仍显示窗口。
- launcher 用 `MR3A_SHOW_WINDOW` 向 MaaPiCli 和 Agent 传递本次选择；每次启动明确重设值，避免普通启动从调用者继承后台模式。
- `InstanceSession.ensure_ready()` 按策略选择底层启动参数，故障恢复继续复用同一路径；后台模式保留 Android 会话、DHCP、ADB、启动完成等待及截图分辨率准备，仅跳过 show-full-ui。
- 小鲤仓库的包装入口自动附加 `--no-window`，start 仍等待 run 返回，stop 不变。没有修改游戏配置、账号数据、主环境启动方式。

## 验证

- `PYTHONPATH=agent .venv/bin/python -m pytest tests/test_named_instances.py tests/test_instance_runtime.py tests/test_waydroid_instances.py tests/test_instance_adb_api.py tests/test_instance_takeover.py -q --tb=short`：54 passed。覆盖后台会话仍启动、是否显示窗口的分支、策略继承与普通入口覆盖，以及现有命名隔离、控制租约与 ADB。
- 小鲤包装入口及控制器的 15 项 Python 测试通过，启动参数包含后台标记、停止参数独立、不能切换其它实例。
- 已有 xiaoli Android 上运行 `run xiaoli --check --no-window` 成功，前后 niri 的 Waydroid 窗口 ID 集合没有新增；命名设备截图仍为 1280×720。
- 没有为验证关闭正在使用的窗口、重启 Android 或运行游戏任务；本轮实机验证是热启动检查，冷启动无窗口路径由单测覆盖，未做设备冷重启实测。

## 边界

后台启动不依赖一个可见的桌面窗口，但仍复用本机 Wayland 用户会话与现有 Waydroid 管理。它不负责关闭此前已经打开的窗口，也不更改 stop 的完整环境关闭语义。
