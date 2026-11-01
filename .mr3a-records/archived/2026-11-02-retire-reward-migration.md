# 奖励迁移完成后移除迁移机制及残留

## 现象 / 需求

用户确认迁移已经完成，不需要继续保留旧图迁移、历史备份或完成标记。上一轮加入的一次性迁移防护随迁移机制一起退场，不把已经完成的一次性工作留在每次启动流程中。

## 原因

主环境及命名实例当前已使用各自的运行目录，旧 `assets/debug/reward_shots` 不再是有效奖励来源。继续保留迁移入口及补偿机制没有当前业务用途，反而增加维护负担和奖励分类污染风险。

## 改动

- `InstanceRegistry.prepare` 移除 `migrate_legacy` 参数，删除旧奖励合并、冲突归档、历史分类修复、迁移标记代码及不再使用的 hashlib 导入。
- 启动器只准备实例环境，不再调用迁移流程。日常奖励保存、列表和清理继续使用实例自己的目录。
- 删除专用迁移测试，保留一个回归验证：即使磁盘仍有旧源，重复准备实例也不改当前奖励及登记；当前奖励被清理后，准备环境不会重新导入旧图或生成迁移产物。
- 按用户要求清理本地主环境旧源 `assets/debug/reward_shots/`（15 张过期 PNG 和旧登记）及 `deps/bin/debug/legacy_rewards_migrated.json`。`reward_shots_archive` 实查不存在，无额外备份待清理。当前正常奖励目录、账号配置及其它日志保留。

## 验证

- `PYTHONPATH=agent .venv/bin/python -m pytest tests/test_named_instances.py agent/tests/test_reward_shots.py -q --tb=short`：20 passed。
- 当前正常奖励目录清理前后 10 张 PNG 相对路径、SHA256 完全相同；相较上一轮的 9 张，多出的是运行中脚本正常新增的奖励图。
- 代码已无迁移调用/实现，`git diff --check` 通过。未重启脚本或操作游戏；历史开发归档保留作为事实记录，以本篇及当前代码为准。
