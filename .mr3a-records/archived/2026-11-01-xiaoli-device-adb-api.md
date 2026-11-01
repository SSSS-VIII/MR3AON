# 小鲤固定游戏控制器复用设备层

## 需求与原因

小鲤通过固定 run 入口操作独立 Android，不自行管理实例、ADB 端口或 Waydroid。已有命名实例与控制租约应继续作为唯一设备层；外部控制器需要二进制标准输入、完整 stdout/stderr 和退出码，原私有 `_adb` 只返回成功输出，不适合作为公共传输 API。

## 改动

- `InstanceSession.adb()` 在 `control()` 租约内执行绑定设备的 ADB 命令，返回 `CompletedProcess`，支持 bytes 标准输入及 1–300 秒超时。
- 拒绝 ADB 全局参数、连接、目标选择、服务器及端口管理。实例和 serial 仍由设备层确定。
- 原 `_adb` 与恢复路径保留兼容行为，共用 `_adb_result`。宿主文件路径权限由上层固定控制器限制。
- `/home/linn/xiaoli/run` 和控制器在小鲤仓库维护；固定使用已有 `xiaoli` 名字，不启动 MaaPiCli 业务任务，也不克隆 main 凭据。

## 验证

`PYTHONPATH=agent .venv/bin/python -m pytest tests/test_instance_adb_api.py tests/test_named_instances.py tests/test_instance_runtime.py tests/test_waydroid_instances.py -q --tb=short`：42 passed。

新 API 经小鲤固定服务实机调用：启动已安装的 OPPO 渠道忍三 `com.pandadastudio.ninjamustdie3.nearme.gamecenter`，截图 1280×720；仅打开应用和只读观察，没有登录、同意协议、创建角色或消耗资源。控制器持有 `xiaoli` 租约，与 MR3A 同名脚本互斥；main 的业务配置未修改。

未重跑与本功能无关的全套业务用例，已知 5 项失败基线见 current-work。原已暂存的未完成讨伐鬼族文件保留，未纳入本次提交。
