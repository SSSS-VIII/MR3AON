# 外部调用的单次执行与退出结果

## 需求与原因

外部项目需要临时选择任务与选项，任务完成或确认无需执行后退出，释放同名控制权并保留游戏环境。已有 Agent 会保留持久化完成任务的下一周期候选、等待延后任务，以及将运行一小时的逆袭/藏宝图重新入队。因此仅指定 `--task` 无法保证有限次执行。定制 MaaPiCli 的 Runner 结束值也不能单独证明业务完成。

## 改动

- `run [名字] --once --task 任务` 显式执行本次计划，支持重复 `--task` 及前一功能的 `--task-options`。只选择名字，继续使用同一份 MaaPiCli、源码、命名环境与 `InstanceSession.control()`。
- 单次模式过滤已持久化完成的顶层任务，应用既有节点完成状态。真实完成状态仍正常落盘，但不保留下一周期候选，不等每日/每周重置。日常长期模式保留原调度语义。
- `ScheduleDeferredTask` 在单次模式记录 deferred，不创建下次周期计时器。一小时让出信号继续保留，在原安全节点记录 yielded，随后停止当前轮次，不重新入队。两种结果均明确表示业务未全部完成。
- Agent 通过本次专有结果文件记录结果，失败不能被后续 queue_finished 覆盖。正常返回须同时具备 CLI 成功退出、有效 Agent 完成证明及原生服务正常关闭后的 cleanup_complete 标记。任务硬失败、恢复耗尽、异常断连、收尾超时或缺少证明均返回失败。快速硬失败时 Agent 可能先断连，因此可靠结果缺失同样作为失败收口。
- 单次 launcher 监督独立 CLI 进程组并持有同名控制租约；本次 CLI PID 经 exec 包装绑定，TUI 仍只停止本实例。SIGINT/SIGTERM 请求本实例正常停止，超时清理本进程组。收尾结束并释放控制租约后才输出结果行。TUI q 的退出也接入结果记录。
- 临时任务配置进一步改为继承的匿名文件，内部参数为 `--task-config PATH`。保存的任务输入凭据不会被展开到进程命令行，选项转流水线继续使用原生 Configurator。MaaPiCli 配套提交为 `54d74251` 和 `ebb4d272`，本机已增量构建。
- 拒绝 `--task-options null`、数组、缺少显式任务等无效调用，避免外部参数错误意外落回保存计划。

## 调用与退出约定

```bash
./run xiaoli --once --task 每周逆袭悬赏 \
  --task-options '{"每周逆袭悬赏":{"选择要打的逆袭boss":"仅逆袭S"}}'
./run xiaoli --once --task 备战副本 \
  --task-options '{"备战副本":{"免费接力":true}}'
```

0为正常结束/确认无需执行，1为执行、初始化或收尾失败，2为参数错误，3为周期延后，4为一小时安全让出，130为SIGINT/q中断，143为SIGTERM中断。3/4需要调用方后续重试，不能当作业务完成。正常收尾后的独立 `MR3A_RESULT ` 行携带 status、exit_code、reason；初始化/参数错误可只有 stderr。完整类型与示例见 `../test-environment.md`。

## 验证

- 选项、单次调度、监督进程及参数保护均有离线回归。覆盖真实仅S/免费接力选项转换，已完成过滤，持久化状态继续写入且不保留周期候选，周期延后不启动计时器，一小时让出不重排，硬失败不被完成覆盖，以及 CLI 返回0但缺少/损坏完成证明时返回失败。
- 最终全量普通回归205 passed、14 skipped、5项既有失败、85 subtests passed。5项仍为悬赏商店滑动方向、旧刷新按钮节点，以及3项 enable/enabled 双字段历史断言，未改动这些无关语义。
- `MR3A_ONCE_LIVE=small ... pytest tests/test_single_run_live.py` 9项通过。经 launcher 解析参数，运行真实共享 MaaPiCli/Agent，借用 small 的真实就绪过程及控制租约，以临时无点击资源验证 completed、skipped、failed、deferred、yielded、SIGINT、SIGTERM、TUI完成、TUI q。
- 每个实机用例检查退出码/JSON、配置内容不变、实例子进程回收、控制租约可重新取得和 Android 会话保留。TUI 两项还检查备用屏退出与 termios 恢复，无 semaphore 泄漏警告。
- 配套 MaaPiCli 4项 CLI 回归通过，编译成功，两个仓库 diff 检查通过。
- 验证过程中暴露并独立修复了冻结命名容器启动阻塞，见 [冻结实例唤醒](2026-11-06-resume-frozen-named-instance.md)。最初的后台/窗口夹具失败属于该问题，修复后最终9项通过。

## 环境与边界

main 当时有运行中控制者，未接管或中断。xiaoli 保持停止。使用已存在的 small 做无点击验证，并保留其 Android 运行状态。业务夹具配置位于 /tmp，没有替换账号保存配置，没有复制程序，也没有实跑每周逆袭或备战副本。新号起号的实机验收仍按此前交接保留。

工作区原有小鲤好友清理记录与周末竞速说明继续单独保留，未混入本次功能。
