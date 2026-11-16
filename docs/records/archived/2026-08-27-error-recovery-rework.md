# 错误恢复重构

## 日志结论

- 本次卡死是流水线活锁，不是进程阻塞：`藏宝图调用fight` 在约 2 小时 42 分内执行了 2798 次。
- 登录页左下角图标被 `进入战斗中.png` 以约 0.999 的相似度误命中，节点持续“识别成功”，所以 `on_error` 没有触发。
- 旧 `back` 最长等待 8 分钟；重启时又读取了当前业务 task 的默认 vivo 包名，而不是启动 task 实际选择的官服包名。
- 重启失败后任务队列继续执行，后续任务在 Waydroid 桌面上继续长时间等待。

## 本次实现

- 默认错误处理改走独立的 `全局错误恢复`；普通业务 `[JumpBack]back` 不再承担“回主页后重试 task”的隐式职责。
- `back` 与 `全局错误恢复` 单轮超时均缩短至 30 秒；全局恢复确认主页后，每个 task 只允许回入口重试一次，之后升级为重启。
- 启动 task 在 PI option 生效后，用 `RememberGamePackage` 记录实际包名；重启不再读取当前业务 task 的默认包名。
- `RestartGame` 每个 task 只允许执行一次，直接 StopApp/StartApp 已记录的包，并把恢复启动流程接回原 task 入口。
- 恢复启动限制为 2 分钟；重启或恢复启动失败后，由 `AbortTasker` 异步停止整个 Tasker，阻止队列继续在错误页面执行。

## 验证

- 5 个错误恢复单元测试通过：包名记录、主页单次重试、正确包重启并回入口、单次重启限制、停止任务队列。
- Python `compileall`、全部资源 JSON 解析、恢复链静态断言、`git diff --check` 均通过。
- MaaFramework 5.12.2 `Resource.post_bundle` 成功加载整套 `assets/resource`。
- 未启动正式 `maapicli`，未执行真实设备重启，未修改正式入口缓存。

## 藏宝图 fight 活锁补充修复

- 旧节点的真实意图是：`进入战斗中.png` 仍存在时每两秒继续等待，图标消失后才进入 `fight`。问题在于正向识别成功后 JumpBack，持续成功不会累计 next 全 miss timeout。
- 删除两个正向匹配并 JumpBack 的伪 delay 节点，替换为 `inverse: true` 的“等待进入战斗图标消失”节点。
- 两个 `调用fight` 节点设置 `rate_limit: 2000`：图标仍存在时，inverse next 识别失败，每轮间隔 2 秒；图标消失时 inverse 命中，才进入对应 `fight`。
- `default_pipeline.json` 显式设置 `timeout: 30000`。若登录页图标持续误命中，等待消失节点会按上述 2 秒间隔持续 miss，并在 30 秒后进入 `Default_on_error`。
- 真正的 `fight` 自身已有 `rate_limit: 200` 和 `timeout: 40000`，其战斗响应速度不变。
- 自动化测试增加至 7 个，MaaFramework 整包加载再次通过。

## 未采用的额外强化

按本轮范围暂不处理：

- task 级或重复节点级 watchdog。
- `进入战斗中.png` 的页面上下文联合识别。

当前单图仍可能误命中，但错误的“持续成功 delay 子节点”已移除；后续 `fight` 识别全部 miss 会由 30 秒 timeout 进入全局恢复，不再形成本次日志中的无限 JumpBack 循环。
