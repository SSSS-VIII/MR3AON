# 小鲤安装魅族渠道忍三并切换启动渠道

## 需求

将 xiaoli 的忍三改为魅族渠道服，保留现有 OPPO 版及游戏中心。

## 原因 / 来源

下载目录没有魅族包；原小鲤启动任务及模板选择 oppo，共享服务器选项也没有魅族。只安装而不增加选项，会使下次 run 仍然打开 OPPO 版。

确认来源为魅族官方页面：

- 原商店条目：https://app.meizu.com/games/public/detail?package_name=com.pandadastudio.ninjamustdie3.mz
- 当前官方游戏平台：https://store.mlinkapp.com/
- 官方首页返回忍三 id 3206501、包名 `com.pandadastudio.ninjamustdie3.mz`。使用其前端公开调用的 `https://api-store.mlinkapp.com/games/public/download/expand/url` 取得下载地址，文件来自 `s3-res.mlinkapp.com`，没有使用第三方重打包站点。

## 改动 / 操作

- 官方 APK 保存到 Downloads/NinjaMustDie3_Meizu_2.0.106.apk，大小 2087405822 字节；SHA256 `af0a5bffaa08e9bb5b1af43da396925dec96b50a995de90dfb8e2624231d4694`。二进制不入 Git。
- 持有 `InstanceSession('xiaoli').control()` 安装并打开。Android 确认 versionName 2.0.106、versionCode 266，包名带 `.mz`。
- 共享日常任务的渠道选项增加「魅族」，同时覆盖 package 和 custom_action_param.package，沿用原有启动、记录包名及恢复机制。默认官服与其它渠道不变。
- 仅小鲤实际配置的启动渠道改为「魅族」，保留「上次登录」及空密码。小鲤仓库 game/mr3a-task.json、对应保护测试和 game/README.md 同步修改；不纳入其原有根 README 和 agent 未完成工作。
- 原 OPPO 忍三、OPPO 游戏中心及服务均保留，没有卸载或清数据；没有改 main 配置。

## 验证 / 边界

- 安装返回 Success；pm 同时列出 OPPO 忍三、OPPO 游戏中心及魅族忍三。启动前台为 `.mz/.MainActivity.init`，截图有效。
- 应用停留在首次隐私提示页，未代为同意条款、输入账号或登录；未验证魅族账号登录、后续可能需要的渠道组件或完整启动流水线。截图位于 xiaoli/debug/adb-shots/meizu-ninja-installed.png。
- MR3A 启动相关 4 项测试及 10 个子测试通过；小鲤设备控制器 12 项测试通过，两个仓库 diff 空白检查通过。没有为安装任务重跑全量游戏流程。
- 小鲤配套模板、保护测试和文档提交为 `2f19c05`。MR3A 代码、测试和此记录同次功能提交；鬼族暂存内容仍保留，不一并提交。
