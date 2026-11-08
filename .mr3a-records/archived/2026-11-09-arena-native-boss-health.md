# 离线疾风Boss训练血量

## 需求与依据

用户要求竞技场Boss血量统一改1。环境已按要求回退输入基线、角色HP5000；此功能仅作用于隔离arena客户端的GameOnly离线疾风，不改变角色血量、陷阱伤害或其它模式。

## 改动

新增Local/native_boss.lua。保留原BossBattleOfficialStart已有实现，调用后通过原InitBonus(HP,1,0,0)、InitStageHp、SetHealth(1)设置最大及当前血量。MaxHp由原GetBonus(HP)取得，不能只写当前血量而留下旧阶段血量。安装前检查目标热更槽为空；重复加载不重复包装。原AI、受击、死亡、结算及地图事件仍由客户端执行。

本地加载器在environment后加载此模块，不改已恢复的environment输入/重开/角色逻辑。

## 验证

- LuaJIT运行实际模块，验证原bonus→阶段HP→当前HP调用次序；普通模式及已死亡Boss不修改。
- 原客户端第2关DragonBoss原50000/50000，在原正式开战后实际1/1，继续原物理步后仍1/1；未通过直接调用死亡方法替代战斗。
- 后续选关验证中原ArmorDragon已出现原死亡流程，未添加强杀/跳过Boss代码；不能据此宣称每种Boss、每个阶段均已逐一击杀验收。
- 截图/探针位于忽略目录gameonly/native-mechanisms/boss-health-one.*等；模块不含客户端资源、密钥或账号数据。main未操作。
