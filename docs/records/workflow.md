# 项目开发工作流

现行协作入口为根目录 `AGENTS.md`，本文件补充项目工作方式；当前待办看 `current-work.md`，环境与启动命令看 `test-environment.md`，具体原因和验证证据看 `archived/`。规则保持一份清晰入口，历史归档不作为额外规范注入。

## 开工与收口

结合记录、Git历史和代码核实当前任务；优先查看相关摘要与模块演进，不要求通读全部历史。保留工作区已有改动，按改动风险做适当验证，区分已完成、待验证和未完成。

提交按功能点组织，及时收口已完成内容；未完成或无关改动留在工作区。Git提交说明用于解释具体变化，长期文档用于保存代码不容易表达的取舍、运行边界和后续事项。提交或交接时判断是否需要更新文档，优先维护现有专题；不要求新增记录，也不绑定记录数量与提交数量。推送、发布按用户要求执行。

## 分支使用

日常开发以 `main` 为主分支。为上游评估/移植建立的临时分支在该轮工作收口后合回 `main`，切回 `main` 再继续开发，并删除已合入的临时分支。保留原始功能提交与已有合并提交，不通过 squash/rebase 重写历史。选择性移植须保留对应上游版本、来源和验证记录，不把它标记为完整合并上游。切换前核对工作区和暂存区，保留未完成内容；同步远端前先fetch核实分歧，推送仍按用户要求执行。

## 本地运行与关键约束

- 主要运行链是 `./run` → Waydroid / ADB 准备 → 本地定制 MaaPiCli → Agent 接管队列 → 业务流水线。GitHub Actions 是另一条检查/发布链，不能代替本地开发流程介绍。
- 本机使用 `/home/linn/MaaPiCli` 的 `mr3a-managed-queue` 定制实现；官方二进制不能直接替代。框架绑定与本地二进制协议必须匹配。依据：[10-05 上游合并](archived/2026-10-05-upstream-merge-and-maapicli-5142.md)。
- 正式与测试共用 `./run [名字]` 的实例管理，省略为保留现有账号的 main。同名复用环境，新名空白凭据；`tools/run-* [名字]` 只在内存中选择本次任务，不复制程序或覆盖保存计划。受控只读冒烟可用测试夹具加同一二进制，不向日常列表添加假入口；旧 `.run-test` 机制已停用。具体使用前读 `test-environment.md`。
- 每个业务任务独立顶层提交；恢复重排交给 Agent，避免用嵌套 `context.run_task()` 继承停止状态与 JumpBack 栈。任务停止前推进队列；长期任务在安全点让出，不破坏抢队热路径。依据：[调度试点](archived/2026-08-27-deferred-task-scheduler.md)、[长时恢复](archived/2026-08-29-long-run-recovery-and-treasure-map.md)。
- Tasker 事件回调不能直接发 Maa 请求；硬结束路径在另外线程推进。Wait 正常路径睡醒后经 StopTask sink 提交下一项；异常兜底及断连尚有待办，见交接页。依据：[RPC 回调问题](archived/2026-09-19-tasker-sink-ipc-stack.md)、[硬失败](archived/2026-10-25-tui-recover-after-managed-task-fail.md)、[Wait 修复](archived/2026-10-28-wait-post-task-abort.md)。
- `enable` / `enabled` 双写是解决节点持久化禁用失效的兼容策略，不能仅因旧测试断言不同就撤销。依据：[10-11 双字段兼容](archived/2026-10-11-mirror-node-enable-disable.md)。
- 游戏日常状态主要按 05:00 重置，在调度安全点刷新，不中断当前业务任务；同入口不同配置实例须保留各自基础 override。不同阶段的周/月重置规则按最新归档与代码核对。

## 验证与记录

纯文档整理检查 diff、文件路径与相对链接即可，不必反复启动游戏或全套测试。代码修改按影响范围选择保护测试；全量基线可用：

```bash
PYTHONPATH=agent ./.venv/bin/python -m pytest tests agent/tests -q --tb=short
git diff --check
git diff --cached --check
```

明确记录「静态检查」「单测」「设备实测」各自结果。当前已知失败和未完成实现集中写在 `current-work.md`，修复后同步更新，不让后续会话重新发现同一问题。
