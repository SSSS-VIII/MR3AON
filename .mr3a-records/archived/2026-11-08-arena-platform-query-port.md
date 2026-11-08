# 原版平台候选查询与三组结果合并

## 需求 / 原因

随机板训练需要真实接触条件，不能仅渲染板子或按肉眼矩形猜碰撞。原版LevelBlockCollider.GetGroundYIncludeAir调用LevelManager.GetAtAirGroundY，它查询三组内部平台数据并合并，独立于UnityCapsule setter。

## 改动

C# ClientPlatformQuery复现GetGroundY选择规则和GetAtAirGroundY/GetMaxTopY三组合并。内部端点按运行方向乘法比较，不自行归一化min/max；横向两端和topY==角色Y边界均可入选。排除明确的下穿对象；topY必须<=角色Y，不使用视觉半径扩大范围。同组最高平台等高保留先遇到的；跨组GetMaxTopY等高选后一个，因此三组不能简单flatten后取第一个。

NativeOracle执行原版方法：单组GetGroundY，以及完整GetAtAirGroundY连同原GetGroundY/GetMaxTopY代码。只有托管枚举器和GameManager当前方向为夹具，候选边界比较与选取执行原始ARM64指令；三组对象为不重复的测试对象，没有虚构真实场景的池归属。

## 验证

400个单组查询边界/排除/双向/零方向/随机案例，152个三组空列表/等高/随机组合，与编译后C#输出完全一致。连同原有部件总1942项通过。所有库仅使用已保存分析副本，没有操作main。

## 继续开发 / 未完成

本次是候选平台选择，不是落地、承载、移动后的同步或完整碰撞通过。还须结合实际字段坐标、平台初始化/重置、LevelBlockCollider最高平台与底层地面比较以及角色FallFromAirGround状态核对。107种已定位预制体的依赖闭包427包已启动只读导出，完整源索引另以4个宿主CPU工作进程补齐；这些是普通文件处理进程，没有代理委派或Android接管。资源定位/导出结果另记录，不预先写成完成。
