# 小鲤重新安装 OPPO 游戏中心

## 需求 / 原因

用户在网络重启后仍对 OPPO 游戏中心不满意，要求重新安装该应用。

## 操作

- 使用 `InstanceSession('xiaoli')` 持有控制租约，确认就绪后停止游戏中心进程。
- 使用原 Downloads 中的 `Gc_new_uid_14.3.3_46abf7d_250214_ARM64-20250214-539412491.apk` 执行覆盖重装，保留该应用现有数据；未执行 pm clear 或卸载游戏本体。
- 通过包管理器解析 `com.nearme.gamecenter` 的启动组件，冷启动游戏中心；没有沿用手写的 Activity 名称。
- 未修改小鲤 OPPO 渠道配置、账号密码、游戏数据或 main 环境。

## 验证 / 边界

- 安装返回 Success；am start -W 返回 Status: ok、LaunchState: COLD，前台启动组件为 `com.heytap.cdo.client.ui.activity.MainTabPageActivity`。
- 本次只完成覆盖重装与启动验证，不能据此宣称手机号密码登录问题已经解决。没有填写或提交账号信息。
- 无源码改动，按设备维护操作归档；本记录独立提交，鬼族未完成内容保留。
