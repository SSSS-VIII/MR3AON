# 运行与测试环境

## 命名入口（当前约定）

```bash
./run                         # main，复用当前配置、账号和 Android
./run small                   # 创建或复用 small；新名不继承主账号凭据
./run small --configure       # 配置 small 自己的任务与登录选项
./run small --check           # 只准备/检查 Android，不运行游戏任务
./run small --prepare         # 只初始化运行文件，不启动 Android
./tools/run-weekly-reverse     # main 本次只跑每周逆袭，不改保存的任务计划
./tools/run-3v3 small          # small 本次只跑完整 3v3
./tools/adb-screencap small    # 截图到 small/debug/adb-shots
./tools/record-3v3-parkour small # small 的交互按键录制，需要独占该名字
```

新名字初次使用进入独立配置菜单；非交互调用时若尚无任务会明确报错。新 Android 仍需安装游戏并登录自己的账号。名字可用中文、字母、数字、下划线和短横线。同一个名字完全复用，不同名字可并行；同名控制者重复启动会被拒绝。main 的旧脚本若还在运行，应先按 q 退出旧会话，再用新入口接管，不会强杀现有任务。

`test` 现在只是普通实例名，不再表示复制测试环境。旧 `deps/.run-test` 入口已停用，旧文件保留、不清空；单任务工具改用同一实例和同一可执行文件，任务选择仅在内存中生效。

截图可在同名脚本运行时读取；录制会要求该名字的独占控制权，不能和脚本同时点击。录制结果写在实例自己的 `debug/3v3-record`。

## 文件归属

- 项目与源码：`/home/linn/MR3A`。
- 共用程序：`deps/bin/MaaPiCli` 仍是指向 `/home/linn/MaaPiCli/build/bin/RelWithDebInfo/MaaPiCli` 的软链接；没有复制二进制或动态库。
- main：`deps/bin/config/` 保留原 PiCli 配置和 `agent_task_state.json`；`deps/bin/data/` 为可写缓存/学题，`deps/bin/debug/` 为新日志和奖励。原有 pip 设置也保留。
- 其它名字：`.mr3a-instances/<名字>/{config,data,debug}/`；注册表 `.mr3a-instances/registry.json` 和各环境 `instance.json` 固定身份，目录不入库，配置和运行目录私有。
- 资源、模型、图片共享只读；每个环境生成小型 interface 路径配置，不复制资源或源码。旧主奖励图首次正式接管时合并，冲突图保留历史版本；原图和旧日志不删除。
- Android 状态由名字内部管理。包管理器的 Waydroid 文件保持不变；仅当前 1.6.3 经验证，版本升级后需要复核适配。主机重启尚未实测，重启后仍通过同一个名字启动。

## 验证

```bash
PYTHONPATH=agent .venv/bin/python -m pytest tests/test_named_instances.py tests/test_instance_runtime.py tests/test_waydroid_instances.py -q
# 显式选择已就绪的名字；只截图，不向游戏发送点击
MR3A_LIVE_INSTANCES=main,small PYTHONPATH=agent .venv/bin/python -m pytest tests/test_named_instances_live.py -q
# CLI 目录和临时任务选择（不连接游戏）
cd /home/linn/MaaPiCli
python3 dev/test_runtime_cli.py
```

受控设备冒烟使用独立测试夹具和同一程序，分别验证框架日志、Agent 日志、奖励图和状态落盘；不加入日常任务列表，不改主账号任务或密码。

## 后续接口

外部封装只选择名字，并使用 `runtime.InstanceSession` 的就绪、状态、截图和控制租约；不自行维护 Waydroid、ADB 或端口。接口边界见 `docs/develop/命名实例.md`。智能体服务和大小号协同业务尚未实现。

## 历史验证记录（不是当前入口约定）

### 2026-08-27 错误恢复重构验证

- Python：3.14.6
- MaaFramework Python binding：5.12.2
- 虚拟环境：`/home/linn/MR3A/.venv`
- 已执行：全部资源 JSON 解析、Python `compileall`、恢复链静态断言、7 个错误恢复/流水线保护单元测试、MaaFramework `Resource.post_bundle` 整包加载、`git diff --check`
- 本次未启动正式 `maapicli`，未执行真实设备重启，未修改运行缓存

### 当时的验证命令

```bash
PYTHONPATH=agent ./.venv/bin/python -m compileall -q agent tests
PYTHONPATH=agent ./.venv/bin/python -m unittest -v tests/test_error_recovery.py tests/test_pipeline_guards.py
PYTHONPATH=agent ./.venv/bin/python tools/ci/check_resource.py assets/resource
git diff --check
```
