# 小鲤魅族游戏框架安装失败处理

## 现象 / 需求

魅族忍三已安装，但登录时反复要求安装魅族游戏框架，自动安装未完成。用户要求处理。

## 原因 / 证据

- 包管理器最初没有 `com.meizu.gamecenter.service`，SDK 日志反复报告该包不存在。
- 自动安装流程还记录调用 Flyme 专用 `Intent#setForceMode(Boolean)` 的反射异常；Waydroid 非 Flyme，不能依赖这条安装路径。后续框架自更新又进入了 Android 的「允许从此来源安装」设置页。
- 官方旧商店的网页下载入口不可用，当前游戏平台下载 API 不提供这条框架记录。官方帮助建议从游戏中心检查框架更新，但新版本设置中未找到可用入口，改用官方 SDK 附带的安装包进行引导安装。

## 操作

- 从官方游戏平台安装魅族游戏中心 12.3.1os，保留 OPPO 中心与两套忍三。
- 通过官方开发文档目录找到「魅玩游戏框架SDK接入手册」id 42：`https://apiopen.mlinkapp.com/api/web/v1/doc-wiki/detail?id=42`，文档公布 SDK8.0.6_20240927 的下载链接，文件来源 `mlinkapp-autogame-store.fos.flymeyun.com`。
- 下载至 Downloads/MeizuGameSDK_8.0.6.zip，提取其中「接入必须使用的jar包和assets（重要）/assets/MzGameCenterService_8.0.6.apk」，用 ZipFile 读取并校验压缩包条目。没有安装 FlymeAuto 车机测试包，也没有使用第三方镜像框架包。
- 框架保存至 Downloads/MeizuGameFramework_8.0.6.apk（19444942 字节），SHA256 `c20729e38fd7142ff0e3512a69fe1a6662574cea6ad83ec371c2087faf63a244`；经命名设备对象持有 xiaoli 控制租约安装，返回 Success，初始版本 8.0.6。
- 打开忍三触发渠道登录检查。拒绝框架通知权限；在框架请求的 Android 设置页允许它自身安装更新，再返回游戏。随后系统安装器完成框架更新，版本变为 8.2.4。
- 排查时观察到另一个控制者间歇切换页面，控制租约冲突时本次命令按约定失败，没有绕过租约；已向用户提示协调。没有操作 main、卸载 OPPO 或填写游戏账号。

## 验证 / 边界

- 最终包管理器确认 `com.meizu.gamecenter.service`：versionName=8.2.4、versionCode=8002004，installerPackageName=com.android.packageinstaller。
- 同时保留魅族游戏中心、魅族忍三、OPPO 游戏中心和 OPPO 忍三。用户反馈看起来已正常；未代为输入账号，也不将安装成功等同于已完成账号登录。
- 诊断日志和截图只留 xiaoli 的 debug，二进制在 Downloads，不入 Git。本次没有改脚本代码，不运行无关业务测试；记录与运行环境说明同次提交，鬼族暂存内容仍保留。
