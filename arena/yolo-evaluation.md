# 现成YOLO与原客户端参考图实测

2026-11-10：默认已升级为官方YOLO26n-OBB十三类物理/运动模型，11810原训练帧、71原资源族、69族有原生物理目标正标签。先按旧val和全新罕见val选权重，再评分保留test；没有自写网络。2201保留测试帧物理目标空间召回86.9%/精确率95.5%，角色96.6%，绳/地面/浮台原中心线召回98.4%/85.0%/86.4%。共享13类不输出具体原资源ID，逐资源只能按真值报告召回。

当前物理目标分组包含水果，并非纯伤害陷阱口径。第三关级水果板实机失败，原配置与原回调证明它有切割/收集目标，当前共享类/避让策略不适用，后续需明确分离。

新增罕见test252帧物理目标空间召回78.5%/精确率92.5%；香蕉68.1%、木偶炸弹91.5%、激光67.2%。木偶炸弹的运动类别仍明显判错，cue保留test为0/21，岩虎缺实景，荆棘独立采集早死未见目标。低召回还包括连电球37.5%、飞竹42.0%、滚动基座58.1%，不能称全机关验收。权重、分割、失败及SHA见[独立验收记录](../.mr3a-records/archived/2026-11-10-arena-obb-default-v10-independent-evaluation.md)，实际控制与时延见[视觉入口](visual-baseline.md)。

以下八/六类及零样本段落保留演进依据；旧v4可显式选择原权重回退。原客户端继续负责实际画面、物理和随机生成，NN与Trainer均为官方Ultralytics。

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
