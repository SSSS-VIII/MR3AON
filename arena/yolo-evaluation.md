# 现成YOLO与原客户端参考图实测

2026-11-10：标准YOLO26n-OBB候选已完成7059原训练帧的24epoch微调，并用2332验证原帧评分：危险物空间召回88.8%/精确率95.3%，角色95.7%，绳/地面/浮台中心线召回98.1%/83.9%/92.1%。目录保留69直接类型+153原生派生，59资源有危险物训练正标签；共享13类不输出原资源身份，逐资源召回按原真值分组，不冒称每资源精确率。cue仍0/20、部分高关级缺项，完整独立测试待后续候选确定。

新候选实际有伤通过固定三板及随机四板，god全false；原取图→Unity按键P95约59.5/43.7ms，见[当前实机基线](visual-baseline.md)。原客户端继续处理画面/物理/随机生成，NN与Trainer为原版Ultralytics，不自写网络。以下八/六类和零样本段落为演进记录，现有默认暂留八类v4。

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
