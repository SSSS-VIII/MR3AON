# 现成YOLO与原客户端参考图实测

19类v13飞竹阶段候选已完成独立测试与第5关两板各三种子的无伤实跑，默认仍v12，完整5/6及旧资源回归继续。权重/预测接口/边界见[飞竹v13记录](../.mr3a-records/archived/2026-11-10-arena-bamboo-phase-controller-v13.md)。

2026-11-10后续：默认更新为16类v12，12958原训练/7335验证帧，新增5/6关原生坡段。固定选择后新363测试帧地面中心线召回83.9%、危险物82.6%；旧30回合全6583帧危险物R87.1%/P96.1%，仍未无伤。控制工作点已对齐模型0.25、目标收集仍0.8。详情见[坡段微调](../.mr3a-records/archived/2026-11-10-arena-slope-finetune-v12.md)及[视觉入口](visual-baseline.md)。下文v11、v10及早期适配是历史。

2026-11-10后续：默认已升级为官方YOLO26n-OBB十六类交互模型，12534原训练帧、71原资源族、69族有物理正标签。保留原形状，香蕉Box、番茄/西瓜Capsule作为切割目标，木偶炸弹仍是危险Sphere；按原CFG/脚本证据区分，零伤害未知物不会自动当目标。

旧val2332帧物理召回88.6%/精确率96.4%，旧2201帧跨资源回归87.1%/96.1%。新保留test30002仅三水果/弹球/木偶炸弹361帧：物理1463/1568=93.3%，高置信目标1196/1201=99.6%，危险物误当目标0；新val为666/671、0危险误分。都是帧目标口径，含同一对象的相关帧，不代表独立试验成功率。

新的物理/危险物/目标分开统计；先按val选权重及0.8信任阈值，再看新test，空间匹配不会掩盖危险错分。cue仍未匹配，岩虎缺实景，荆棘独立采集不足；木偶炸弹在新val的具体细类仍仅29/171匹配（多数当弹球，仍作为危险物），不称完整运动识别通过。

冻结后新种子第三关级三板与原水果80/80完成，第一关随机四板660伤害；全god=false，仍伤害明显。权重、对照、源摘要和限制见[16类及控制验收](../.mr3a-records/archived/2026-11-10-arena-slice-target-planning.md)，命令及回放见[视觉入口](visual-baseline.md)。此前v10物理统计包含水果，原失败的直接原因后经原生诊断核为地面入口侧面遗漏，不能继续归因任务未满80。以下八/六类及零样本内容是历史。

用户明确允许微调现成YOLO、禁止自写网络。此前标准YOLO26n六类适配曾接入默认，随后八类状态版本及隐藏爪补充利用原生控制器自动标注普通/预备/冲刺，官方Trainer微调18epoch。独立seed53空间召回98.2%、预备92.1%、冲刺97.4%，该段没有弹球/机关/投射物，不代表全部陷阱。见[状态微调](../.mr3a-records/archived/2026-11-09-arena-yolo-crow-state-adaptation.md)、[六类适配](../.mr3a-records/archived/2026-11-09-arena-standard-yolo-finetune.md)。

八类v4隐藏爪独立claw63严格召回13.0%→97.3%、精确率92.2%，旧飞行/蜘蛛验收保持，实际仍有伤。见[隐藏爪适配](../.mr3a-records/archived/2026-11-09-arena-yolo-hidden-claw-adaptation.md)。该八类权重实景只有6资源，不能称全部机关通过。

以下保留此前不更新权重的零样本试验，准确性失败；其中“未训练/未接管”描述的是当时状态，不是当前状态。

## 资源与配置

完整来源与碰撞边界见[对象目录](entity-catalog.md)。84幅原生参考图已通过YOLOE官方视觉编码器转成84类提示profile，只做固定样例特征编码，没有梯度更新。原检查点SHA保持不变。提示输入是预制体参考图，不是待识别画面的真实坐标。

代码为`tools/arena_yolo.py`，配对验收为`tools/arena_yolo_audit.py`。SDK支持文本/视觉提示的依据为[YOLOE官方说明](https://docs.ultralytics.com/models/yoloe/)，本轮采用视觉提示；没有训练新的候选分类器或策略网络。此前自写网络草稿已移至忽略目录，模型训练尚未开始时即按用户要求停止。

现成权重为YOLO26n及YOLOE-11s-seg；后者取自[原作者权重仓库](https://huggingface.co/jameslahm/yoloe)。本机用独立Python3.12环境、Ultralytics8.4.208/PyTorch2.15.0及RTX5070 GPU，Agent的Python3.14环境没有安装这些依赖。脚本关闭联网/遥测并要求已有本地权重。

## 验证结果

先检查通用YOLO26n：三个实际游戏画面主要检出HUD为clock/整图为tv，没有形成可用陷阱检测。随后检查YOLOE参考图提示、分辨率变化和原资产视觉profile，保留失败结果，不把“能跑推理”当作“识别通过”。

最终profile来自`prefab-references-complete`，84类；验收取独立seed43两段记录中的96帧（曲线板和前三块路线，后一轮采集主动中断，未当成完整通关）。产物为`debug/arena-client/yolo/asset-evaluation-complete/`：

预测设置为640输入、置信度阈值0.1、5帧预热，使用单个GPU推理进程。

- 预热后离线文件图像到预测结果，中位13.19ms、P95 19.77ms；含读取、前后处理及结果拷回CPU，不含实时取图和按键执行。
- 画面ROI中179个原活动敌人碰撞体目标，匹配4个，其中3个原资源名一致。匹配要求同类族、中心误差小于25px、预测框尺寸不超过原碰撞体包围范围3倍。
- 1536个敌人类预测中只有4个匹配；另外367个其它类预测未用敌人标签评判。大量漏检与误检，不能接管操作。

这不是视觉框mAP：原碰撞体与可见轮廓不同，标注亦未完整处理透明度/所有激活状态。即使考虑这些限制，当前差距也很明显。通用预训练权重加静态参考图没有自动获得该游戏的完整识别能力；可继续利用现有资源做标准YOLO的游戏类别适配，本轮未启动训练。

## 复现

在已有独立环境中，所有输出使用新目录：

```bash
YOLO_CONFIG_DIR="$PWD/debug/arena-client/yolo/config" PYTHONPATH=tools \
  debug/arena-client/yolo/.venv/bin/python tools/arena_yolo.py asset-profile \
  --weights debug/arena-client/yolo/yoloe-11s-seg.pt \
  --references debug/arena-client/yolo/prefab-references-complete \
  --output debug/arena-client/yolo/profile-new

PYTHONPATH=tools debug/arena-client/yolo/.venv/bin/python tools/arena_yolo.py evaluate \
  --weights debug/arena-client/yolo/yoloe-11s-seg.pt \
  --profile debug/arena-client/yolo/profile-new/profile.npz \
  --frames debug/arena-client/vision-v2/data/curve43/000100.png \
  --output debug/arena-client/yolo/evaluation-new
```

环境依赖为`tools/arena-yolo-requirements.txt`。截图配对采集为`tools/arena_collect_vision.py`，在暂停推进后保存原图与标注，用UnityEngine.Time.time排除暂停RPC耗时；原检测/轨迹回放检查为`tools/arena_vision_dataset.py`。`arena_snapshot_labels.py --scene`还可保存场内原Collider与脚下LevelBlockCollider字段。标注与目标帧坐标只用于验收，未传入YOLO推理。
