# 已有进程则跳过 StartApp

## 现象 / 需求

游戏已在主页时启动脚本，会间歇性把游戏卡死（画面仍是主页，点击无响应）。卡死与「设置狂点」无关。

## 原因

Agent 一启动固定先跑 `启动游戏`，`启动应用` 无条件 `StartApp`（Monkey MAIN）。进程已在前台时仍会走 Activity pause/resume；Unity 主线程若 2s 内 pause 不掉，就会僵死。冷启动或 `RestartGame` 先 StopApp 的路径不受影响。

## 改动

- `启动应用` 改为自定义动作 `StartAppIfNeeded`：`pidof` 到包名则跳过，否则 `post_start_app`。
- 包名以 Maa 传入的 `custom_action_param.package` 为准；`请选择服务器` 的 override 必须写 `custom_action_param.package`（只写 `param.package` 时 Custom 动作仍吃到流水线默认 `.vivo`，官服会秒失败）。
- 流水线默认包改为官服 `com.pandadastudio.ninjamustdie3`。
- `关闭节点点击主页设置` 的 Disable 目标改为真正的 `启动游戏点击主页设置`。

## 验证

- `tests/test_pipeline_guards.py`、`tests/test_error_recovery.py` 相关断言。
- 实机：官服配置下 `StartAppIfNeeded` 日志包名无 `.vivo` 后缀。
