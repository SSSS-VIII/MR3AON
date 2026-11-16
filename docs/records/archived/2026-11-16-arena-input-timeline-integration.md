# 观测与已发按键时间队列的内部实验接线

## 原因

原commit_action立即修改Perception动作状态；之后内容早于动作消费时刻的图片会被套新phase。已有独立原型和23项CPU证据见[原型记录](2026-11-16-arena-own-input-timeline-prototype.md)。本次开始正式模块接线，先不改变图像时间、不设置固定龄期，避免把未知内容延迟与动作队列一起混入。

## 改动

新增`tools/arena_input_timeline.py`，由独立原型整理。默认Perception不挂input_timeline，原行为保持；只有实验factory显式创建OwnInputTimeline。runner在observe最开始消费截止图片时间的已发事件，决策project在游标副本上重放稍后的已发键；commit_action仅入队和计算报告，不立即改真实观测动作账本。CRC重复也走project，避免重复消费/再次发键。setup记录own_input_timeline状态，source清单包含模块。

Obb缺框前段使用已重放的预测上下文，真实last_observation仍保持原图来源。所有重放在最后图像的相机平面内，camera_reference_y不在forecast中自行推进；识别层只加实际视觉support测得的camera delta一次。相机参考若已被预测修改则明确拒绝，新增正负相机位移构造回归。没有给角色设置native位置、动作、跳数或无敌；原Perception.action、advance_player和物理常量复用。

## 实机发现并修正的漏检边界

v50先跑关闭路径51043无伤；开启队列回合到13.25秒附近连续漏检后触发None.center异常，未出完整report，不算穿越。wrapper正常捕获异常并恢复1101/5000。最后可见行为为下翻→上翻→反向下翻，随后已发上翻在一张player=None的旧帧之后进入消费时刻。旧原型直接用该无人物状态计算primitive，碰到缺失几何。

修复为独立replay_geometry：原图未识别到人物后，仅用先前预测几何重放已经发出的键，保留unconfirmed标记并按新观测相机位移转换；真实latest仍player=None，project输出仍unknown，不允许过期估计成为决策可见人物。新回归覆盖“发键后旧帧丢身体、后来才消费该键”，验证不丢历史、不编造角色、不确认接触。错误回合和partial日志保留。

## 当前验证边界

首次接线前全617项通过/2可选依赖缺失跳过；边界修复后27项队列及动作/OBB相关共44项通过。v51修复后正在独立原生回归，最终结果另补。固定27/35/45ms图像补偿均未引入；此路径目前为内部候选，不宣称无伤或时钟完全对齐。


## v51修复后原生结果

session39196退出0，51043/seed40201与61081/seed39203均完整无伤，31前序依赖加队列共32份source与快照及结束工作区相符。捕获请求到Unity按键P95分别82.50/77.36ms，max87.28/77.81ms；21/27次原回执均唯一匹配。五关有7个unknown人物决策行，仍未伪装为可见角色，重放队列跨21/27个决策行实际运行。结束1101/5000、menu/keyboard true、eval false。

两个种子对应近期旧路径也曾0伤，不能写成队列提高整体无伤率，仅证明修复后的接线与缺框路径在这两回合运行通过。还需另一个六关种子、蝙蝠/金锤及坡面衔接回归，仍不默认启用。

后续在vision日志新增observed字段，分别保存外推前的像素状态/身体/动作/支撑与决策投影，避免再把预测恢复的普通身体当成实际看见的身体；仅日志，不改变策略。地形重复采样网格不重复写入，其原线段和选中ID仍保留。

## v52独立扩测

session45741退出0，61081/seed40200穿越1440伤，6011/seed40202穿越480伤，53031→53041→53051/seed41002三板穿越4043.75伤。32份source与各次setup、冻结快照及结束工作区全部相符；941/575/2704行同时记录真实observed与决策投影，无observed时钟晚于决策。三组捕获请求→Unity按键P95为82.55/94.61/65.54ms，不能据此推断截图内容龄期。

结束恢复1101/5000/menu与keyboard开启/eval关闭。队列不是无伤修复；同种子61081历史默认端点路径960伤，v52为1440，不能晋升默认。53041本次穿越，原v45连续碰撞路径死亡、v42旧端点三板3924.92伤；多项历史源码不同，不作单变量性能结论。保留内部可选，后续先解决可测量的截图内容延迟与坡面/落地感知。证据：`debug/arena-client/yolo/finetune/rope-recovery-v37/native-timeline-v52/{summary.json,source-verification.json,restored.json}`。
