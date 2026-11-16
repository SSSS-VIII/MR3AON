# 缺失角色时提前结束规划预算判断

## 现象与原因

地面陷阱候选的边界测试暴露：MpcAvoider.choose虽有unknown_player守卫，runner却会先调用uses_search选择计算预算。在已有neural_segments地面且角色None时，ground_bamboo/_objects会先访问p.x，产生NoneType.x，而不是交还缺框状态。这与此前own-input回放的缺角色路径不同。

## 改动

uses_search入口先拒绝player=None；不伪造角色、不推进接触/跳数、不变更正常可见角色决策。地面搜索实验的其它功能已因原生退步撤回，只有此独立守卫保留。

## 验证

ground/jump1_falling两个缺框场景均验证预算探测False且choose返回unknown_player；旧实现ground场景可复现异常。与原落地/下翻回归一并通过；不连接设备，不把静态边界保护称为无伤改进。
