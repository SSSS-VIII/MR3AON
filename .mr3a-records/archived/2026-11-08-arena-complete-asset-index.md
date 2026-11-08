# 竞技场实体资源完整索引

## 需求与原因

原版随机板子、敌人和特效恢复需要完整客户端资产映射。此前只扫描部分包，162种Stage实体类型中仅107种找到预制体，不代表其它资源不存在。

## 改动与结果

按APK与DynamicContent的当前来源优先级完成44449个资源包索引，新增补扫描13557包。重新按真实配置的resourceName定位预制体：157种有配置的敌人/物品全部唯一定位，无歧义。其503包依赖闭包已完整保全，结果在忽略目录`debug/arena-client/arena-entities-complete/`，映射在`decoded/arena-resource-plan-complete-index.json`。

## 验证与未完成

- 全量扫描结束后PatchVersion未变；动态同名包优先于APK，避免混用旧资源。
- 503包导出0错误：783 Texture2D、847 Sprite、373 ParticleSystem、590 Material、122 BoxCollider、72 SphereCollider、9 CapsuleCollider、79 AnimationClip等。原始零尺寸Font Texture明确登记无法预览，未生成替代像素。
- 5种敌人ID（226、238、257、210、209）在当前配置表缺失；包含它们的部分Stage仍在当前竞技场章节路由候选内，不能直接当作废弃地图。待继续追实际生成与兼容路径。
- 此次为资源映射/保全，尚未宣称实体已在完整训练环境运行。原版渲染管线、逻辑、随机地图组合及交互仍继续开发。
