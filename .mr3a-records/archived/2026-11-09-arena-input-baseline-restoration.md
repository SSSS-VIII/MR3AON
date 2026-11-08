# 回退选关试验并恢复输入基线、5000血与K跳跃

## 需求与原因

用户在选关开发期间报告原跳跃/下翻/暂停输入和界面消失，明确要求退回开发前，改用原传送符与通灵兽机制，血量设5000。未要求用户提供具体陷阱现象。此前裁剪Stage、补GameStart、菜单与重置修改混杂，必须先撤回再验证基线；不能把原手感已确认的运行环境继续当试验场。

## 回退与改动

以9c40e66（疾风+2000血、选关尚未开始）恢复本轮六个已跟踪源码/测试文件。五个新增选关/UGUI/目录代码及测试从工作源码移除，源码/原diff/清单完整保存在忽略目录gameonly/selection-reverted-2026-11-09。未改常驻任务暂存文件，未回退其它项目功能。

在干净基线上仅把一级小黑HP加成从20倍改为50倍（100→5000），同步启动及训练断言；K与空格/W/↑走同一个原UIGameOperate跳跃按下/释放接口。没有角色位置、物理状态、原陷阱或生成逻辑改写。原APK及Lua资源桥仍使用已记录版本。

通过InstanceSession("arena")只重启游戏进程，清除旧热更委托、旧UGUI和协程；不是只删文件却继续沿用被修改进程。后续必须从此基线接原传送符/通灵兽，旧裁剪方案撤回，不宣称旧选关完成。

## 验证

- 原客户端实际启动疾风并进入战斗，CurrentHp/MaxHp5000。
- 反射核验LevelManager.GetLevelDataID/GetLoadStageStream两个试验hotfix槽均nil；MR3A_PauseMenu对象不存在，原GameOperate activeInHierarchy=true。
- 80原物理步后原按钮截图可见；arena自己的Android K键触发原jump:14，S触发rollToGround:6，keyboardError为空；P两次实测TimeScale1→0。
- 15项控制/适配器/K输入回归通过；真实截图及状态在gameonly/recovered-input。main未输入/重启/注入。

仍待：原生轻改跳关、通灵兽落地buff回收、陷阱行为独立审计、Boss1血、同板内部随机/固定标注。此次提交仅保证已回退的输入基线与新血量，不把待做项当完成。
