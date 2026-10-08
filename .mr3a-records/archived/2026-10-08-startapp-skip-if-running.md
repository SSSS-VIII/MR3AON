# 已有进程则跳过 StartApp

## 现象 / 需求

游戏已在主页时启动脚本，会间歇性把游戏卡死（画面仍是主页，点击无响应）。卡死与「设置狂点」无关。

## 原因

Agent 一启动固定先跑 `启动游戏`，`启动应用` 无条件 `StartApp`（Monkey MAIN）。进程已在前台时仍会走 Activity pause/resume；Unity 主线程若 2s 内 pause 不掉，就会僵死。冷启动或 `RestartGame` 先 StopApp 的路径不受影响。

## 改动

- `启动应用` 改为自定义动作 `StartAppIfNeeded`：`pidof` 到包名则跳过，否则 `post_start_app`。
- 包名仍从 `启动应用` 节点读取（兼容任务里 `param.package` override，以及 `custom_action_param.package`）。
- `关闭节点点击主页设置` 的 Disable 目标改为真正的 `启动游戏点击主页设置`（原先 Disable 了不存在的 `点击主页设置`）。
- 去掉误加的设置点击 rate_limit / max_hit / 「避免狂点」focus。

## 验证

- `tests/test_pipeline_guards.py`、`tests/test_error_recovery.py` 相关断言。
- 未在设备上复现「主页开脚本」全流程。
