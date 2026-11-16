# 原疾风飞竹锁定到发射的固定计时核验

## 用户问题和核对方法

用户指出实体入画后反应通常太晚，应主要用锁定状态预报发射和危险窗口。本次重新交叉核对原IL2CPP构造/状态代码、全部可达疾风资源配置、已有原生周期与热更委托记录；未只依据我自己的1秒实现推断原版。

## 原实现

EnemyFlyBambooDataStruct构造在0x4766070–0x4766080读取rodata 0x1117c58，将相邻两个float写入0x1c/0x20，实值2.0/.5，分别为aimTime/aimLockTime。ProcessState的0x4777d60–0x4777d64进入aimLock时将配置aimLockTime装入_currStateTime，调用ShowLockAnim。aimLock计时结束后0x4777e8c–0x4777e98切readyAttack并直接写0x3f000000，即固定0.5秒；readyAttack减Time.deltaTime到负后，0x4777d78–0x4777d98切flyToNinja，0x4777ebc调用StartAttack。

因此真正aimLock是0.5秒，随后另有0.5秒readyAttack；我们YOLO的locked类把两段合并，从进入合并阶段到发射约1秒。锁定段读取参数并非代码写死，不能泛化到任意改版/运行时参数；本版原疾风配置核对结果如下。

## 配置与原生证据

由现有gale-catalog-native的30源地图追溯全部_stageRandomGroup候选，得到511不同可达板，逐个确认mode6后扫全部块/替代块enemyInfos：35板1430处type102，全部未显式覆盖_aimLockTime，统一沿用构造0.5；其中5/6关级333处也完全相同。锁定前aimTime确有2秒639处、1秒772处、1.5秒19处，不能拿统一开局瞄准时长推锁定。

既有原生61个完整锁定→发射周期为1.000–1.033447秒，符合两段0.5秒及离散帧更新；不是本次新跑或所有负载下的严格墙钟上界。既有原生反射记录中ProcessState/ResetEnemyInfo/StartAttack/ShowLockAnim热更委托均不活跃，构造实值也为2/.5。当前行为无相关代码变更。

新核验证据存debug/arena-client/yolo/finetune/bamboo-lock-contract-v16：原构造反汇编、逐配置placements.json、gale-parameter-audit.json及source-contract.json（源摘要/原地址/已有61周期统计）。这是静态原资源及已有原生交叉证据，不冒称新原生实测。

## 对预报的含义与未完成项

以真正锁定起点t0为锚，先得到约t0+1秒的发射窗口，再由原出生位置、速度/场景流、碰撞长度和人物未来位置求扫过人物的危险窗口，并在执行动作时考虑取图/推理/按键延迟。实体检测主要做校验和反校准，不能承担临近实体才开始避让的主要职责。

现代码本已使用约1秒，问题重点是视觉时间锚：locked类包含锁定/准备，首次看到locked不保证刚进入aimLock；阶段误判、漏起点和重叠目标会使剩余时长估计不准。后续应定位锁定变化帧/必要时利用原动画进度，保留边界误差，不能每次看见locked就重新等1秒。本次无控制器/模型改动，无设备操作、训练或新运行验证；仅记录核验结论，未把偶发400归因或写成已修。
