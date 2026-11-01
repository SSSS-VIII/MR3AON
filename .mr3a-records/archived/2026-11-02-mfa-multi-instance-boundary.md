# 命名实例与 MaaFramework / MFA 多实例发布边界核对

## 现象 / 需求

用户关心目前 Waydroid 多实例封装是否与 MaaFramework 原生多实例、MFA 的模拟器启动路径配置冲突，要求为日后 release 保持兼容方向。本次核对和记录边界，不提前实现整个 MFA 发布适配。

## 原因 / 核对结果

- 当前 `assets/interface.json` 仍声明标准 `Adb` 控制器，`InstanceSession.bind_config()` 把名字解析出的 ADB 地址写入该环境 PiCli 配置，截图/输入等业务 Pipeline 仍由 MaaFramework 执行。因此底层控制器方式没有冲突。
- 自定义封装解决的是本机 Waydroid 生命周期、名字与设备绑定、私有运行目录及外部控制租约；MaaFramework 控制器本身不会替项目创建独立 Android 系统或自动隔离 Agent 业务数据。
- 上游 MFAAvalonia 的 README 已说明标签页独立实例；`StartSettingsUserControlModel.cs` 的 SoftwarePath、EmulatorConfig 按 CurrentInstance 保存；`AgentHelper.cs` 启动 Agent 时传递 `MFA_INSTANCE_ID` 和 `MFA_INSTANCE_NAME`。核对的是上游 master 当前源码，尚未验证项目实际 release 所下载版本。
- 不能据此宣称当前项目直接使用 MFA 就已兼容：`MR3A_WORK_ROOT`、`MR3A_ADB_SERIAL` 等只由本地 launcher 注入；`adb_device.adb_target()` 缺少绑定时仍要求恰好一个设备；启动游戏闪退恢复还调用 `RestartWaydroid`；没有 MFA 身份/目录映射或输入租约衔接。当前入口还依赖定制 MaaPiCli，发布工作流则集成 MFA，生命周期/调度也需要单独验收。

## 改动 / 后续约束

- 在 `docs/develop/命名实例.md` 写明上述边界和 release 验收条件：保留标准 Pipeline/Controller；MFA 负责其模拟器及控制器，Waydroid 留作可替换后端，避免双重启动/恢复；按稳定实例 ID 绑定业务目录和实际设备。
- 未来要验证同安装目录两实例并行、身份与状态复用、恢复不串设备、文件不串目录、停止单实例不影响其它实例。不要把本机双 Waydroid 实测作为 MFA 发布验收。
- 同时纠正文档内上一轮遗漏的旧奖励迁移描述，反映迁移已经退场。

## 验证

只读检查本地实例/启动器/运行路径/ADB 辅助/闪退恢复/打包脚本，并对照上游官方源码，未修改运行逻辑、未操作游戏。文档 diff 检查通过，不为本次说明重跑设备或单测。

上游依据：
- https://github.com/MaaXYZ/MFAAvalonia/blob/master/README.md
- https://github.com/MaaXYZ/MFAAvalonia/blob/master/MFAAvalonia/ViewModels/UsersControls/Settings/StartSettingsUserControlModel.cs
- https://github.com/MaaXYZ/MFAAvalonia/blob/master/MFAAvalonia/Extensions/MaaFW/AgentHelper.cs

## 用户确认的后续方向（取代上文全面接入 MFA 的建议）

用户在本次核对后明确：保留定制 MaaPiCli，参考 MFA 实现自己的模拟器兼容层，暂不全面兼容 MFA。已经同步开发文档和当前交接，后续按名字统一启动路径/参数、设备连接及运行目录隔离，Waydroid 作为一个后端；当前先修悬赏结算问题，不扩展其它模拟器。仅文档调整，diff 检查通过。
