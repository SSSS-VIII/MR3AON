# 小鲤恢复 OPPO 渠道并卸载魅族应用

## 需求

用户决定保留 OPPO，配置也使用 OPPO，允许删除魅族应用。

## 原因 / 范围

此前试用魅族渠道后，xiaoli 实际配置和小鲤任务模板均为「魅族」，同时安装了魅族游戏、游戏中心与框架。本次只调整小鲤实例，不回滚其它环境或删除共享渠道支持。

## 操作

- 取得 `InstanceSession('xiaoli').control()`，仅将实际「启动游戏 / 请选择服务器」选项改回 `oppo`，其它字段保持原样，包括账号输入、任务列表和「上次登录」区服。
- 卸载 `com.pandadastudio.ninjamustdie3.mz`、`com.meizu.gamecenter.service`、`com.meizu.flyme.gamecenter`，三项均返回 Success。
- 保留 OPPO 忍三 `com.pandadastudio.ninjamustdie3.nearme.gamecenter`、游戏中心 `com.nearme.gamecenter` 及 `com.heytap.htms`，没有卸载、清数据或覆盖安装 OPPO 包。
- 同步小鲤仓库 game/mr3a-task.json、保护测试及 game/README.md，默认渠道恢复 oppo；无凭据模板不覆盖实际账号信息。
- MR3A 当前交接与运行环境说明更新为 OPPO，魅族安装和框架处理归档保留为历史。没有删除 Downloads 的安装文件。

## 验证

- pm 实际包列表确认三个魅族包均不存在，三个 OPPO 包仍在。
- OPPO 忍三启动 Intent 成功，目标为 `.nearme.gamecenter/.MainActivity.init`；未代为登录或执行其它游戏业务。
- 校验实际配置仅渠道发生变化，main 配置 SHA256 不变。
- 小鲤控制器 12 项测试通过，两个仓库 diff 空白检查通过。本次无 MR3A 源码变化，不重跑无关游戏或全量业务测试。
- 记录与当前环境说明同次提交；小鲤模板、测试及文档在对应仓库提交 `9baa833`。鬼族未完成内容继续保留。
