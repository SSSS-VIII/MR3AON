# 每日悬赏协同移除多余UID

## 现象与原因

用户指出小号已由命名实例确定，好友邀请应直接匹配昵称，不需要再配置UID、进入好友资料核对。首版实际已先筛选小号动态昵称，并未写死「小卫鲤」或特定ID，但追加的UID配置与资料校验多余，先前「逐个核对ID」的说明也漏掉了昵称筛选步骤。

## 改动

- 「小号配置」只保留「实例名称」，删除游戏ID输入及流水线attach字段。当前命令示例只需 `{"每日悬赏":{"拉小号模式":true,"小号配置":{"实例名称":"xiaoli"}}}`。
- 小号启动后直接从主页读取当前昵称，通过协同状态传给大号；不打开自己的个人资料。昵称、账号都由当前实例登录状态决定，不硬编码。
- 大号一次读取当前页好友昵称，匹配小号昵称，复核同行昵称、头像和邀请按钮后直接邀请；不进入任何好友个人资料、不读取UID。同页多个同名候选、昵称识别不完整或行位置变化则回退原流程。
- `CompanionManager.start` 改为只接收实例名与任务ID；会话和状态不再传game_id。保留受管会话检查、准备确认、下一轮等待、超时、原组队回退及小号后台回收。
- 临时任务配置构建时只保留当前接口定义的保存输入字段，兼容已经保存的旧游戏ID，不修改磁盘配置；本次显式传入游戏ID仍报未知字段。其它输入的局部覆盖及校验保持。

## 验证

- `pytest tests/test_bounty_companion.py tests/test_companion_runtime.py tests/test_companion_lifecycle.py tests/test_task_options.py tests/test_single_run_process.py -q`：152 passed。覆盖多种动态昵称、昵称缺失/截断/备注、行重排/头像变化/同页重名、无个人资料点击、旧保存字段兼容、单次退出及回收。
- 原生资源整包加载、`git diff --check`通过。未重跑全量历史失败用例，本次没有改动这些路径。
- main/xiaoli仅邀请实机通过：命令只提供实例名，xiaoli日志现场读得昵称并经历ready→joining→teamed，main确认相同昵称的小号已加入并准备，随后停止验收，没有开战或消耗奖励次数。
- `MR3A_RESULT` 返回completed/0，cleanup_complete及companion_cleanup_complete均true，companion_count=1；主保存配置字节不变。证据在 `deps/bin/debug/companion-nickname-acceptance/nickname-console.log`，临时配置副本已删除。
- 小号后台回收，main退出验收队伍恢复主页，双方控制权释放。原配置和正式完成账本保持；本轮没有把新选项写入保存计划。
