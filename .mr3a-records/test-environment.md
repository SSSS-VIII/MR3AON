# 运行与测试环境

## 命名入口（当前约定）

```bash
./run                         # main，复用当前配置、账号和 Android
./run small                   # 创建或复用 small；新名不继承主账号凭据
./run small --configure       # 配置 small 自己的任务与登录选项
./run small --check           # 只准备/检查 Android，不运行游戏任务
./run small --no-window       # 后台启动，不打开 Waydroid 桌面窗口
./run small --prepare         # 只初始化运行文件，不启动 Android
./run small --stop            # 关闭 small 窗口和 Waydroid 后台，保留数据
./run --stop                  # 关闭默认 main 的 Waydroid
./tools/run-weekly-reverse     # main 本次只跑每周逆袭，不改保存的任务计划
./tools/run-3v3 small          # small 本次只跑完整 3v3
./tools/adb-screencap small    # 截图到 small/debug/adb-shots
./tools/record-3v3-parkour small # small 的交互按键录制，需要独占该名字
```

新名字初次使用进入独立配置菜单；非交互调用时若尚无任务会明确报错。新 Android 仍需安装游戏并登录自己的账号。名字可用中文、字母、数字、下划线和短横线。同一个名字完全复用，不同名字可并行；同名控制者重复启动会被拒绝。main 的旧脚本若还在运行，应先按 q 退出旧会话，再用新入口接管，不会强杀现有任务。

`test` 现在只是普通实例名，不再表示复制测试环境。旧 `deps/.run-test` 入口已停用，旧文件保留、不清空；单任务工具改用同一实例和同一可执行文件，任务选择仅在内存中生效。

截图可在同名脚本运行时读取；录制会要求该名字的独占控制权，不能和脚本同时点击。录制结果写在实例自己的 `debug/3v3-record`。

关闭窗口不等于关闭 Android。需要释放该实例后台时使用 `--stop`；先按 q 退出同名脚本，再关闭实例。停止会退出 Android 会话及对应容器管理服务，不删除配置、账号或日志；下次仍按原名字启动。ADB 服务器作为宿主传输基础设施保留，只清理该实例连接，不结束其它设备连接。

`--no-window` 仍准备 Android、DHCP、ADB 和截图尺寸，只跳过 `show-full-ui`；本次启动的 Agent 恢复也保持后台模式。不带此参数仍按原样打开窗口。小鲤的 `~/xiaoli/run xiaoli` 已自动附加该参数，停止入口不变；已存在的窗口不因此被关闭。

## 文件归属

- 项目与源码：`/home/linn/MR3A`。
- 共用程序：`deps/bin/MaaPiCli` 仍是指向 `/home/linn/MaaPiCli/build/bin/RelWithDebInfo/MaaPiCli` 的软链接；没有复制二进制或动态库。
- main：`deps/bin/config/` 保留原 PiCli 配置和 `agent_task_state.json`；`deps/bin/data/` 为可写缓存/学题，`deps/bin/debug/` 为新日志和奖励。原有 pip 设置也保留。
- 其它名字：`.mr3a-instances/<名字>/{config,data,debug}/`；注册表 `.mr3a-instances/registry.json` 和各环境 `instance.json` 固定身份，目录不入库，配置和运行目录私有。
- 资源、模型、图片共享只读；每个环境生成小型 interface 路径配置，不复制资源或源码。旧奖励迁移已完成并退场，启动不再读取 `assets/debug/reward_shots`，没有迁移标记或历史备份分类；奖励只使用各实例自己的 `debug/reward_shots/`。
- Android 状态由名字内部管理。包管理器的 Waydroid 文件保持不变；仅当前 1.6.3 经验证，版本升级后需要复核适配。主机重启尚未实测，重启后仍通过同一个名字启动。

## 验证

```bash
PYTHONPATH=agent .venv/bin/python -m pytest tests/test_named_instances.py tests/test_instance_runtime.py tests/test_waydroid_instances.py -q
# 显式选择已就绪的名字；只截图，不向游戏发送点击
MR3A_LIVE_INSTANCES=main,small PYTHONPATH=agent .venv/bin/python -m pytest tests/test_named_instances_live.py -q
# main 的无点击退出检查：含真实 TUI、终端模式、q 和子进程回收
MR3A_EXIT_LIVE=1 PYTHONPATH=agent .venv/bin/python -m pytest tests/test_agent_exit_live.py -q
# CLI 目录和临时任务选择（不连接游戏）
cd /home/linn/MaaPiCli
python3 dev/test_runtime_cli.py
```

受控设备冒烟使用独立测试夹具和同一程序，分别验证框架日志、Agent 日志、奖励图和状态落盘；不加入日常任务列表，不改主账号任务或密码。

## 后续接口

新号起号使用独立名字与起号预设，不与日常计划混跑；必填账号代号，状态保存在该实例的 `config/staged_workflows.json`，不是每日重置状态。本轮仅离线验证，尚未使用新号实跑。入口和中断重试边界见 `docs/develop/新号起号.md`，不要用main/xiaoli已有账号验证教程。

外部封装只选择名字，并使用 `runtime.InstanceSession` 的就绪、状态、截图和控制租约；不自行维护 Waydroid、ADB 或端口。接口边界见 `docs/develop/命名实例.md`。小鲤已通过独立插件的 `game_control` 接入：启动调用 `~/xiaoli/run` → 本项目 `run xiaoli --task 启动游戏`，只在单条设备操作期间持有租约；配置为 OPPO、上次登录。账号尚未提供，仅验证到渠道账号页；大小号协同业务仍未实现。

## 小鲤当前游戏渠道

xiaoli 当前仅保留 OPPO 忍三、OPPO 游戏中心及其服务，启动任务渠道为 `oppo`、区服为「上次登录」。实际账号配置保留，模板不含密码。魅族忍三、游戏中心及框架已按用户要求卸载，见 `archived/2026-11-01-xiaoli-return-oppo.md`。此前魅族框架安装处理只作为历史记录保留，不再是当前环境依赖。

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

## 外部项目的本次选项与单次执行

```bash
./run xiaoli --once --task 每周逆袭悬赏 \
  --task-options '{"每周逆袭悬赏":{"选择要打的逆袭boss":"仅逆袭S"}}'
./run xiaoli --once --task 备战副本 \
  --task-options '{"备战副本":{"免费接力":true}}'
```

`--task` 可以重复，按参数顺序执行。`--task-options` 的 JSON 第一层是本次任务名，第二层是接口选项名。select 使用 case 名，switch 使用布尔值或 `"Yes"`/`"No"`，checkbox 使用 case 名数组，input 使用字段到值的对象。选项名与 case 名以当前任务接口为准，例如 `仅逆袭S` 中没有空格。只覆盖提供的值，其余沿用该账号保存选项，没有保存值时采用接口默认值。输入对象支持局部覆盖，选中 case 的子选项也可在同一任务对象内指定。

`--task-options` 和 `--once` 都要求显式 `--task`，与配置/检查/准备/关闭模式互斥。参数只在本次内存配置中生效，保存的账号任务计划与选项保留。内部使用继承的匿名配置文件将选项交给同一 MaaPiCli，保存的输入凭据不进入命令行参数。真实任务完成记录仍按原规则落盘。

`--once` 执行本次指定计划后退出，释放同名控制租约，Android 与游戏环境保留。已有持久化完成状态继续生效，已完成任务直接跳过；完成登记不再保留下一周期候选，不等待每日/每周重置。进入未来周期等待时结束本次调用，返回3。一小时安全让出时返回4，当前任务不再重新入队。3和4都表示业务尚未全部完成，调用方可稍后用同样参数重试。游戏异常恢复仍沿用现有机制，耗尽后失败退出。

| 退出码 | 含义 |
| --- | --- |
| 0 | 正常结束或确认无需执行。入口由持久化状态跳过时为 skipped，其余正常结束为 completed |
| 1 | 执行/环境初始化失败、异常断连、收尾失败或缺少可靠的完成结果 |
| 2 | 参数无效 |
| 3 | 进入未来周期等待，状态 deferred |
| 4 | 到达一小时安全让出边界，状态 yielded |
| 130 | SIGINT 或 TUI 按 q 中断，状态 interrupted |
| 143 | SIGTERM 中断，状态 interrupted |

进入单次执行后的收尾会输出独立一行 `MR3A_RESULT {"status":"completed","exit_code":0,"reason":"queue_finished"}`，适合按此前缀解析 JSON。它位于普通日志之后、控制权释放之后。初始化或参数校验阶段失败时，以退出码及 stderr 判断。多个任务以本次整体结果返回，任何失败都会阻止返回成功；外部信号中断按信号码返回。

无点击真实进程验证使用 `MR3A_ONCE_LIVE=small PYTHONPATH=agent .venv/bin/python -m pytest tests/test_single_run_live.py -q`。它通过 launcher 参数解析及同一份 MaaPiCli/Agent，复用真实 small 就绪与控制租约，只把业务资源和配置换成临时夹具，账号原配置保持原样。覆盖完成、已完成、失败、延后、让出、信号中断、TUI 自动结束和 q；验证终端、进程回收、配置哈希、锁释放及 Android 保留。它没有实跑每周逆袭或备战副本业务。
