# 命名实例启动时唤醒冻结容器

## 现象与原因

验证单次运行时，small 最初完成两个无点击用例，随后 ADB getprop/截图阻塞。状态显示会话 RUNNING、容器 FROZEN。现有 start 只检查管理服务和会话存活，后台模式跳过 show-full-ui 后没有唤醒冻结的 Android，ADB 无法自行解除 LXC 冻结。窗口模式的 show-full-ui 也在该状态下出现超时。

## 改动

命名 Waydroid 启动确认会话就绪后，通过该实例自己的 ContainerManager D-Bus 调用 Unfreeze，然后按本次策略决定是否显示窗口。调用使用已安装 Waydroid 的现有接口，限定当前名字对应的总线，正常运行容器上为幂等操作。账号、任务配置与安装包保留。

## 验证

- 命名后端和运行层27项回归通过，后台/窗口两个启动分支均断言调用当前实例的 Unfreeze。
- 真实 small 从 FROZEN 状态执行 `run small --check --no-window` 成功，ADB 启动检查恢复；后续同一程序的单次无点击夹具继续运行。
- main 当时已有控制者，未接管其脚本。xiaoli 保持停止。本次使用原有 small 验证，没有新建或复制程序环境。
