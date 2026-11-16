# 重开前等待原地面主题预加载完成

## 现象与原因

框架池回收修复后重测，部分跨Boss/后段选板仍在原mount landingEnd等待。原LevelManager.isFinishLoad=false，人物/通灵兽不再离开；不写true绕过原门控，也不调用原跳下接口掩盖原因。

同一原日志在12:40:01显示ThemeGroundController.<CreateGroundObject_Co>d__36空引用，发生在旧场景释放与新场景进入之间。原LoadNextLevel_Co明确先把isFinishLoad=false，等待主题/地面建立后才写true；LevelDataLoading只涵盖数据，不证明其地面对象异步工作已结束。既有native_select仅等LevelDataLoading=false，会在旧主题/地面还在创建时销毁其依赖。

## 改动

native_select在旧场景回收前调用await_native_preload，同时等待原LevelDataLoading=false与isFinishLoad=true，继续使用原600秒总期限与coroutine.step；不修改原完成标志或关卡机制。等待发生在TimeScale已恢复1的原准备阶段，独立本地控制桥未停止。

## 验证

LuaJIT执行真实等待函数：数据已就绪但地面未结束时继续等待、地面已就绪仍等待数据、全部完成不额外推进、原期限到时抛错且不伪造完成。相关2项通过，全部arena410通过/2缺依赖跳过（另含同期飞竹开发项）。

仅经arena入口重启清除旧失败任务后，同一控制会话连续原生定位51091/39250、5009/39251、6011/39252，三次全部进入目标、5000血，分别42.84/48.55/70.63秒（准备耗时，不是视觉链延迟）。测试脚本仅将自身等待上限收紧至30秒，未放宽生产600秒；退出已恢复原函数、完整1101/5000血/暂停菜单/键盘/评估关闭。未操作main。

日志保留旧PID1731的12:40异常，不能把旧缓冲误认成修后复现；本次新PID33000没有该地面空引用。证据preload-guard-v25的summary/logcat/final-state和probe-preload-guard.py。修后原生视觉计分批次继续验证，不把准备成功算策略无伤。
