# 疾风地图池与板子内部随机分布标注

## 需求与依据

用户要求区分怪物随机出现/分布的板子和固定板。不能因为某个位置的候选池有多个Stage，就把每一个Stage都标随机；也不能把随机运动速度等同随机布置。

## 改动

新增离线tools/arena_gale_catalog.py，不加载设备、不安装热更、不改变运行中游戏。从当前CfgEndlessGaleData及已恢复疾风源数据建立路线→关级→地图→板子位置→候选版型目录；原入场Stage单列。每个候选新增classification.layout/label/motion及字段证据：

- 怪物_randomRangeY/_rangeRandomY非零、块组多候选、重复次数范围等属于布置随机。
- _randomRotateDir/_randomSpeedRotate等单列动作随机；无布置变化时仍标“固定布置”。
- “固定布置”仅表示恢复配置没有布置随机项，不保证该敌人全部AI/时序完全确定；没有把动作未核实项伪称固定。

## 验证

当前6路线、30可达地图、238位置、910候选引用、489不同Stage。按配置证据为151随机分布、338固定布置。原646份疾风Stage的块组均为单候选，未发现重复min/max差异，实际随机分布主要来自怪物custom范围字段。

进一步反汇编当前原生EnemyStraightBat/EnemySpider/EnemyDart/EnemyMace/EnemySuspend.ResetEnemyInfo，均调用原RandomManager.Random_Level；直蝙蝠/飞镖等实参为(-range,+range)，锤子的随机方向还调用整数Random_Level(0,2)。原生调用摘录保留在忽略目录native-mechanisms/random-field-native-calls.txt；没有用自行生成的坐标代替原逻辑。

4项回归覆盖关级排序、权重/入场保留、拒绝普通模式/缺失资源、落差入口标注及布置与动作随机区分。完整目录输出忽略目录gameonly/gale-catalog-native.json。尚未接新的轻改选关菜单；旧裁剪菜单已撤回，见恢复记录。未操作main。

## 第8关的无限循环段补充

后续核对level_endless_gale_71发现除了常规开场8000，还通过原_loopRandomStage单列20种无限段版型。已将loop作为独立池纳入目录，不把它遗漏或误作固定第2块后即结束。含循环池共509个不同Stage：155随机分布、354固定布置；此前151/338仅为常规位置候选统计。新增原循环池顺序/权重保护，现5项回归通过。目录采集仍只读，不改运行时。
