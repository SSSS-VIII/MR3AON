# 自动密码登录

## 本次完成

- 在启动流程加入已有账号重新登录路径，识别“账密登录”后点击进入。
- 兼容登录前可能出现的“同意并继续”弹窗，也兼容直接进入密码页。
- 在“请输入登录密码”页面聚焦输入框，复用 `ClearInputTextCompat` 与 `InputTextCompat` 完成清空和输入，随后关闭软键盘并点击登录。
- 在“启动游戏”PI 任务中增加“自动登录密码”input 选项，通过 pipeline override 写入“输入登录密码”节点。
- 本机 `maa_pi_config.json` 已把密码放入 `inputs.登录密码`；该配置目录被 Git 忽略，不会把密码提交到仓库。

## 排查结论

首次实机运行中，账号登录入口、同意弹窗、密码页面、输入框点击和清空均成功，但 `InputTextCompat` 收到空参数并立即失败。

原因不是 ADB 输入失败，也不是 Agent 重排丢失 override。Agent bootstrap 中已经包含“输入登录密码”节点，但生成的 `custom_action_param` 为空。检查 PI 配置后确认密码误填在 input 选项未使用的 `value` 字段，而 `inputs.登录密码` 仍为空。

将密码移动至 `inputs.登录密码` 后，PI 的 `{登录密码}` 占位符可以正确生成 runtime override。

## 验证

- 实机日志已确认各 OCR ROI 均能命中对应页面元素。
- 配置路径确认一致：MaaPiCli build 目录下的 `config` 链接至 MR3A 的 `deps/bin/config`。
- 不在记录及 Git 提交中保存实际密码。
