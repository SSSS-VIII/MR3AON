# 兑换码输入流水线阶段记录

## 本阶段结果

- `InputTextCompat` 处理 MaaFramework Python binding 的 JSON 字符串参数：先对 `argv.custom_action_param` 执行 `json.loads()`，避免把 JSON 编码外层的引号作为实际输入内容。
- `ClearInputTextCompat` 在输入前点击兑换码输入框，并通过 ADB keyevent 清空已有内容。
- 兑换码流水线已验证到提交：输入 `福利签到周周领8月27日开启`，游戏返回 `已达到兑换次数上限`，Maa 任务成功结束。
