# MaaPiCli 控制器创建失败正常返回错误

## 现象 / 需求

并行隔离冒烟测试最初使用错误的测试设备 name，导致控制器未创建成功；PiCli 随后段错误，旧 signal handler 又返回退出码 0，不能仅靠退出码判断运行成功。

## 原因

Runner 对 `MaaAdbControllerCreate` 返回值未检查，后续直接调用空句柄的 post_connection。测试夹具修正为真实设备 name 后完整链路成功，但初始化失败路径仍应正常报错，满足实例通信的可靠性要求。

## 改动

在 `/home/linn/MaaPiCli` 的 Runner 资源释放守卫之后检查 controller_handle，空句柄返回 false；不改变正常控制器或调度行为。增加故意配置无效设备的回归测试，检查非零退出码且没有 signal 11。与目录参数功能分别提交，不纳入 MaaUtils 原有改动。

## 验证

增量重编 MaaPiCli，`python3 dev/test_runtime_cli.py` 三项测试通过。修正夹具后的 main / small 并行截图冒烟已成功，Agent 自定义日志、框架日志、奖励图与状态文件分别落入对应运行目录。没有运行任何游戏点击任务。

MaaPiCli 独立修复提交：`f42934de`。
