# 流水线 deadend 两级兜底

## 目标

避免节点的 `next` 全部识别失败后长期停留；普通节点进入共享 `back`，`back` 自身失败后重启当前任务选择的游戏。

## 实现

- `Default_on_error.next = ["back"]`
- `back.on_error = ["重启游戏"]`
- `主页面检测_back` 是共享回主页 wrapper；仅在检测到当前链路来自 `Default_on_error` 时，将 next 动态改为当前 `TaskDetail.entry`，回主页后重试当前 task，普通 `[JumpBack]back` 行为保持不变
- 新增 `RestartGame` 自定义动作：从当前生效的 `启动应用` 节点读取 package，执行 StopApp → StartApp，然后进入 `启动流程`
- `重启游戏.on_error = []`，避免最后一级失败后再次回到 `back` 形成循环

## 注意

`启动应用` 会在启动后自禁用，因此重启动作不能只跳转到这个节点；必须直接通过控制器执行 StopApp/StartApp。当前实现读取任务覆盖后的 package，可兼容日常任务的多服选择。不查找或复制各 task 的入口，直接使用 MaaFramework 为当前 task 提供的 `TaskDetail.entry`；当前 task 正常结束后，框架再按任务列表继续下一个 task。
