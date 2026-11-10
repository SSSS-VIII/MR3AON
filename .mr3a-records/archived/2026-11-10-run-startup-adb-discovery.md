# 恢复run启动与真实ADB工具发现匹配

## 现象与原因

用户反馈上一轮修复后`./run`无法启动。实际排查发现两个问题。

1. main既有Android网络损坏：Waydroid status返回UNKNOWN，Android eth0仍持192.168.240.112却没有默认路由，宿主ARP INCOMPLETE、ADB devices为空，启动器一直等状态地址。该阶段尚未进入CLI，不能归因于包装器。
2. 仅重启main恢复DHCP/路由后，真实`run --once --task 启动游戏`复现CLI退出255：原生日志12:36:59.903报告`screencap_methods=0,input_methods=0,config=`，Parse config failed / Failed to create controller。此前把真实ADB路径替换成tools/maa-adb，CLI Runner::reconfig_adb按name/path与MaaToolkit发现列表匹配失败，原始默认参数未填充。上次包装器子进程测试和配置绑定单测没有覆盖真实CLI控制器初始化，交付验证不足。

## 修改

撤回ADB包装器绑定、MR3A_REAL_ADB和未接入的包装器脚本/测试，恢复真实ADB路径与匹配name。保留上一轮巡逻三分钟总期限、闪退优先和Default_on_error出口。同步更正上一轮记录和环境说明：原生同步截图无界阻塞仍待合适的底层方案处理，不能宣称已有20秒保护。

当Waydroid状态地址为空/UNKNOWN但会话运行时，InstanceSession仅从同名容器eth0核实地址，并继续校验唯一IPv4和专属子网；无地址、多地址、其它实例子网和已停止会话均拒绝，不读取其它设备地址猜测。

## 现场恢复与验证

- 停止仅在等待地址的旧main启动器和本次check进程，在main控制租约内shutdown/ensure_ready。未关闭其它实例，未kill-server；main重新获得可达地址与ADB连接。
- 实际CLI失败先复现；撤回绑定后`./run main --no-window --once --task 启动游戏`实跑成功：创建控制器、启动Agent、拉起官服、登录回主页，MR3A_RESULT为completed/0、queue_finished、cleanup_complete=true。
- 命名实例、实例运行/ADB API及巡逻恢复50项通过（0.66秒），包含真实ADB绑定、状态UNKNOWN兜底、跨实例地址拒绝、空/多地址及停止状态保护。git diff --check通过。
- 本次只运行原「启动游戏」任务，不启动日常计划或清除完成状态。结束后main Android保留RUNNING、同名控制租约可取得并释放，CLI配置的ADB路径已恢复真实/usr/bin/adb。
