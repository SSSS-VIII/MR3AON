# 选板任务协作取消与控制桥恢复

## 现象与原因

飞竹九池验证到38705/map42/第9板5009时，原通灵兽停在前板8/block3，多分钟不前进。停止宿主验证后读取x5176.9565、target5191.1699、mounted=true、remaining=-1.4，尚未进入目标板，不是0伤验收。落地位置/原通灵兽流程的根因仍待独立调查。

排查中误用MR3A_LocalControl共享EventTrigger.StopAllCoroutines取消选板，同时停掉RPC桥协程，后续RPC失联；这是本次操作造成的故障，不是原游戏自行坏掉。立即经项目InstanceSession入口`./tools/run-arena --restart --paused --seed 42 --level 1 --no-focus`只重启arena应用恢复；未重分配ADB/Waydroid、未操作main，未改原碰撞/输入。失败记录与桥超时保留。

## 改动

增加内部`cancel_native_selection()`，仅允许取消rush/approach；设置当前job.cancelRequested，原旅行循环在自己的下次step检查，沿原pcall收口退出、暂停并释放busy。不会停止共享runner，也不在reset/preload中打断嵌套原重开。下一次仍用原native_select完整回收/重开。未新增用户菜单项或改变原传送符/通灵兽速度、伤害、碰撞和落地算法。

## 验证及限制

真实arena：空闲取消返回false；经原传送符进入5关选板，rush中取消返回true；10秒内原job结束并记录Native selection cancelled、busy=false、timeScale0，随后RPC仍正常，完整原生重开1101成功。最终疾风/基础小黑HP5000、暂停菜单和键盘可用、评估关闭。证据`bamboo-safety-v17/cooperative-cancel-smoke.json`，8项相关保护通过。

本修复解决取消方式，不宣称修复通灵兽的特定落地停滞。九池前5板已保留计分（0/0/400/1250/250），原38705及其后4板未完成；错误启动的后续队列因桥失联未进入游戏计分，也保留在remaining日志。需用新取消接口、有界进度守卫及新前置种子补测，不把选板失败算模型通过。当前主YOLO训练为暂停原生后启动，没有与实时按键计分并发。
