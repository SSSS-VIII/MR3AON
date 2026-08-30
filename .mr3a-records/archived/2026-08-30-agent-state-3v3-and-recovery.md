# Agent 状态、3v3 时序与错误恢复收尾

## 本日完成

- Agent 持久化任务状态落地到 `deps/bin/config/agent_task_state.json`：支持任务级与领取奖励子节点级启用覆盖、有效期、每日 05:00 调度安全点刷新，以及同入口多份 PiCli 配置分别保留基础 override。
- 为当前计划中具有明确成功出口的 8 个顶层日常任务和领取奖励的 5 个子任务登记完成状态；每周兑换码有效到下周三 05:00，其余有效到下一个 05:00。领取饭团、小屋修炼、好友忍币、领取邮件、忍阶任务和持续藏宝图不登记。
- 3v3 自定义操作序列改为绝对时间轴：原始 delay 增加当前 `+60ms` 修正后，再扣除每次 ADB wait 的真实耗时；欠账跨点击偿还，并输出每次点击坐标和时序明细。当前一次性首段校准为 `1000ms`。
- Agent/MaaPiCli 启动乱码完成定位与规避：使用真实项目路径加载 Agent，子进程禁用 ANSI 颜色；本机关闭 MaaFramework stdout，完整日志继续写入 `debug/maafw.log`。
- 正式日志确认旧恢复实现会在嵌套 `context.run_task()` 内执行 `StopTask`，停止状态连带结束外层任务；子任务 ID 又不匹配 Agent 当前任务，导致没有提交下一项而被 PiCli 报告“全部完成”。
- 错误恢复现已简化为 Agent 调度：`Default_on_error` 若识别到主页，则把当前任务放回队首；否则停止游戏并将“启动游戏、原任务”依次放回队首。随后只由当前顶层任务执行 `StopTask`，sink 在停止前提交下一项，不再创建任何恢复子任务。

## 验证

- 全部 pipeline JSON 解析通过。
- `git diff --check` 通过。
- `PYTHONPATH=agent .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：29 项通过。
- 未在自测阶段操作游戏；提交后启动日常环境继续实机运行。
