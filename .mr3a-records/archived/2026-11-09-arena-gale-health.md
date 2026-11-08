# 切换疾风竞技场并将基础血量提高20倍

## 需求与原因

用户确认R/N没有卡死，只是不知道重开后需按P；明确只保留疾风竞技场，不再考虑普通模式，并要求角色血量提高20倍。原入口默认普通Endless=3和100血，需要改实际模式、配置校验、资源预载和训练断言。

## 改动

environment以mode6/EndlessGale进入，校验CfgEndlessGaleData；新GameInfo及PreloadLevelData均传6。原NinjaData和运动/碰撞不改。一级小黑原HP bonus为[0,100,0]，仅HP的基础项/加算项乘20，攻击、回复、跳跃等保持原值；新回合实际MaxHp/CurrentHp=2000。分数转币读取原Gale配置，启动入口及ArenaEnv断言同步2000。

核实GameInfo.get__combatType原生实现会把6归为3，属原竞技场公共逻辑，不是模式设置失败；原GetRealCombatType返回6。state.mode改用原GetRealCombatType，同时以combatFamily单独保留归类值，不覆盖原getter或修改原分支。

## 验证

独立arena实际reset后mode6、combatFamily3、CurrentHp=MaxHp=2000，原跑速14；最终Stage为疾风map3的12012/12022/12032/1204/12051/12063/12071，原疾风地图池选择有效。随后本轮开发的选关探针固定Gale map1/11013也实测通过，选关功能另行提交。14项原控制桥/物理步/适配器回归通过，相关健康/扣血断言已更新。main未操作，原常驻任务暂存改动未纳入。
