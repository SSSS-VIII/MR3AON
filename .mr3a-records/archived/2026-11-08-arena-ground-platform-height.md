# 基础地面与空中平台高度合并

## 需求 / 原因

继续平台真实接触链，仅选最高板子不能处理它与底层地面的关系，等高时当前平台身份会影响下穿与承载。

## 改动

C# ClientPlatformQuery.GroundHeight加入原版LevelBlockCollider.GetGroundYIncludeAir的普通竞技场分支：先基础地面高度，再查询三组平台；只有平台TopY严格高于基础地面，才返回平台及其高度。等高或更低时返回基础地面且当前平台为空。

NativeOracle新增调用完整GetGroundYIncludeAir→GetAtAirGroundY→GetGroundY/GetMaxTopY代码，原始方法体不修改。基础平地高度、托管枚举、单例和非PUGC标志为显式夹具；三组平台筛选、比较和身份结果由原始指令执行。

## 验证

152组三组平台场景分别在两种底层地面高度下，共304项与C#输出的平台身份/float32高度一致。累计2246项原生对照通过。覆盖等高平台相对于基础地面被排除、空平台和排除下穿目标。未操作main。

## 未完成

尚未验证PUGC专属同高下穿分支、斜坡真实高度求值、平台初始化或角色承载。下一步沿OnAirGround实际调用追承载与地形动态变化，不能自行给角色加一个平台速度。
