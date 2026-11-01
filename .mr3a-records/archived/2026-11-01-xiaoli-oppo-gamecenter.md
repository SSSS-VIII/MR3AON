# xiaoli 安装 OPPO 游戏中心

## 需求

将用户 Downloads 中的 OPPO 游戏中心安装到 xiaoli。

## 原因 / 范围

xiaoli 是独立 Android，安装应用须通过同名设备对象定位，不在主环境安装，不复制账号配置。

## 操作

- 使用 `InstanceSession('xiaoli')`，持有控制租约并检查就绪后安装 Downloads 下的 `Gc_new_uid_14.3.3_46abf7d_250214_ARM64-20250214-539412491.apk`。
- 包名 `com.nearme.gamecenter`，版本 14.3.3，versionCode 140302。
- 安装后打开应用，未代为同意条款或输入登录信息。没有修改项目代码、其它实例或账号配置。

## 验证

- 安装返回 Success；包管理器确认已安装的包名和版本。
- 前台 Activity 为 `com.nearme.gamecenter/.DefaultAlias`，截图成功，保存在 xiaoli 自己的 `debug/adb-shots/oppo-gamecenter-installed.png`。
- 运行文件不入库；本次仅提交操作记录，鬼族未完成内容继续保留。
