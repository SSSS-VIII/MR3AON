# 标准YOLO冻结骨干、矩形输入的检测头微调与回归

## 需求与操作

v69/70证明main21在高级关蓝精灵ready阶段漏检/几何偏移，main40虽能提前识别，却未改善整局并使旧飞竹实体召回下降。本轮不写新网络，仍用原YOLO26n-OBB/官方Trainer，从main21微调现有检测头；原完整回合隔离的data-crow-obb-v39（train19020/val9694）及20类/profile不变。

采用官方freeze23，3轮，batch16，imgsz640，rect=True，AdamW/lr0与warmup_bias_lr均5e-5，warmup .5轮，无mosaic，小幅颜色/平移/尺度增强；seed40151。完整命令、超参、源SHA、训练日志在ignored recognition-audit-v37/train-main71-head-rect.py/main71-preflight.json/main71-train.log，结果fit-crow-obb-v71-head-rect。仅在独占GPU窗口执行，未与actor并用。

## 训练与数值验证

三轮约303秒，best来自第3轮，标准fitness=.79652。官方回调Fp32BestExporter保留验证前FP32 EMA，SHA为278c3eff200c0f3e854c4210dd17663db06097cf0eb7b5922ccca1c7c7f9a9d9，官方YOLO重载通过；验证前后浮点状态相同，无FP16越界值。实际78个BN冻结、48个活动，冻结BN字节全部不变，423830个可训练参数；记录的12个训练批形均384×640。没有修改官方架构/Trainer/默认模型或原数据标注。

## 完整原图回归

复用既有probe-main40-rect评分器，固定全部原高关1206、dense677、clean284、legacy6304帧，同原polygon IoU≥.5/conf .25/HUD规则；保留全部raw、all-output及统一原图交集统计，不按类别删框/遮底边。输出main71-regression-{high,dense,clean,legacy}/rect，完整汇总main71-regression-summary.json。

| 回归 | main21物理精度/召回 | v71原图交集物理精度/召回 |
|---|---|---|
| 高关1206 | .69796/.61513 | .73856/.63283 |
| dense677 | .96523/.81300 | .96391/.81483 |
| clean284 | .98890/.82037 | .98337/.81730 |
| legacy6304 | .96615/.92615 | .96331/.92258 |

高关flying_ready严格匹配519→516，火精灵空间召回125/729=.1715、蓝精灵245/878=.2790，仍远低于main40 square的.8519/.9339；冻结骨干这轮没有解决核心目标。旧dense飞竹实体213→215、clean119→119，但legacy整体和clean精度退步，不能靠训练mAP或单项增加晋升。高关推理含CPU回传同步中位6.61/P95 10.64/max12.83ms，不包含读图/几何评分。

因此v71仅封存候选，不接actor、不替换默认。已准备同source/data/seed/全部超参、仅freeze23→0及输出名变化的官方全参数rect对照v76，尚未执行；先完成密集刀阵出生关联的独立原生试验。模型改动与跟踪改动保持分开验证。
