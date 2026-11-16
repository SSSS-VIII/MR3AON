# 现成 YOLO26n 的客户端标注适配

## 需求与授权

用户补充明确：允许微调现成 YOLO，不自写网络。此前禁止更新任何权重的理解不再适用。采用原 Ultralytics YOLO26n 模型与标准 Trainer，只改变游戏数据和训练配置；没有恢复自写网络草稿。

## 改动

`arena_yolo_data.py` 将原生角色/敌人可见状态及 Collider 包围框转为标准 YOLO 标签，六个动作相关类为角色、蜘蛛、飞行怪、弹球、其它机关、投射物。原资产参考图按各自 Collider 配置合成增强，物品作为负样本干扰。六个类不是仅有六种原资源，也不表示所有资源均已通过真实场景验收。

训练/验证按整个回合分组，拒绝同一回合跨组。非站立原角色姿态重复采样补充权重，manifest 明确重复数量；绝不把重复当成新增独立帧。保留原图/原标注、来源 SHA 和样本清单。合成验证使用训练背景，因此混合验证指标不能当独立真实性能；另有完全独立原画面测试。

`arena_yolo_finetune.py` 使用官方 `.train()`：现成权重、冻结前10层、AdamW、batch8、640输入、AMP、单 GPU。`arena_yolo_score.py` 在独立原图上按同类 IoU≥0.5、置信度0.25一对一计数，分开角色/敌人统计，目标是碰撞体投影包围框，不是美术轮廓。

## 训练与验证

独立环境：Python3.12.16、Ultralytics8.4.208、PyTorch2.15.0+cu132，RTX5070 Laptop。基础 Agent 环境不改动。所有图像/参考图/权重/日志在忽略目录 `debug/arena-client/yolo/`。

- v1：curve42+normal42 共852帧原图+1600合成，25epoch、401秒。首轮真实控制发现绳下角色丢失，不能以验证 mAP 宣称成功。
- v2：训练 curve42/normal42/explore45，共1479独立原帧、866姿态重复、600合成；验证 curve43/curve46，共453原帧+100合成。从 v1 checkpoint 继续标准训练15epoch、282秒。
- v2 路径 `finetune/fit-v2/weights/best.pt`，SHA256 `61a8c70a322094e9d0ceeab3153b27671c8aa4cd20096dcac33370599586389a`。
- 混合验证 mAP50 0.9390、mAP50:95 0.7836，仅作训练诊断。
- 独立 seed49 test49 回合每3帧取1帧，共209原画面：角色205/209，precision1.0/recall0.9809；蜘蛛230/244，precision0.9787/recall0.9426；弹球12/12（样本很少）；机关61/122，precision0.7722/recall0.5。敌人合计303/378，precision0.9266/recall0.8016。该回合无飞行/投射物真值，不能声称这两类已验收。
- 离线图像到 CPU 预测中位6.53ms/P95 10.40ms；该评分一部分与实时测试 GPU 重叠，实时完整链路另记，不能将这个数字当最终端到端延迟。
- 数据/原数组/旧视觉/动作相关测试在独立视觉环境执行；本功能2项数据保护及原有32项回归通过。

## 复现

工作目录项目根，`PYTHONPATH=tools`，Python 为 `debug/arena-client/yolo/.venv/bin/python`：

```bash
python tools/arena_yolo_data.py --output debug/arena-client/yolo/finetune/data-new \
  --train debug/arena-client/vision-v2/data/curve42 debug/arena-client/vision-v2/data/normal42 debug/arena-client/yolo/finetune/native/explore45 \
  --validation debug/arena-client/vision-v2/data/curve43 debug/arena-client/yolo/finetune/native/curve46 \
  --references debug/arena-client/yolo/prefab-references-complete --synthetic 600
python tools/arena_yolo_finetune.py --data debug/arena-client/yolo/finetune/data-new/data.yaml \
  --weights debug/arena-client/yolo/finetune/fit-v1/weights/best.pt \
  --output debug/arena-client/yolo/finetune/fit-new --epochs 15
python tools/arena_yolo_score.py --weights debug/arena-client/yolo/finetune/fit-v2/weights/best.pt \
  --episodes debug/arena-client/yolo/finetune/native/test49 --output debug/arena-client/yolo/finetune/score-new
```

## 未完成

机关真实召回率仅50%，动态机关状态/其它关级仍缺足够独立验收。模型已接入视觉控制试验，但有伤通过不等于稳定自动跑图；后续按原机制闭环实测单独记录。没有修改游戏碰撞、物理、无敌和伤害来伪造通过。
