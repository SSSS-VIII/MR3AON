# OBB 原图边界检查与显式 square 推理候选

## 现象与需求

高级关补采后的 main40 完整精度候选，在同一权重、同一原图下使用默认矩形 padding 或 square padding，会把部分假 `muppet_bomb` 放在不同位置。矩形模式中的底边假框仍与真实画面相交；square 模式中的对应假框全部落在原图外的 padding 区。原 `decode` 只拒绝完全画外的人物框，其他类别没有统一原图边界检查，因而图外输出会进入危险物与支撑预测。

本次提供显式 square 推理入口，并对所有类别使用同一真实旋转包络与原图的相交判定。只拒绝完全无交集的框，任何部分相交、边或点接触均保留；不能按怪物类别、底部区域或中心位置删除框。候选识别研究及原始输出见[冲刺识别审计](2026-11-15-arena-crow-recognition-audit.md)，完整精度保存问题另见[FP32 导出](2026-11-16-arena-fp32-checkpoint-export.md)。

## 原因与行为边界

- `tools/arena_obb_detector.py` 原人物检查来自 `4bb43c2`；`57ae4ee` 增加同一模型的局部人物重查。二者没有覆盖其他类别或 ROI padding 平移后落回全图的假人物。
- 检查中心是否在图中会丢失合法跨边界目标；检查轴对齐包围盒会保留一些实际已完全分离的斜框；检查是否有顶点在图中会漏掉横跨画面或完整包住画面的大框。因此需要旋转包络和图框的真实相交判定。
- 本次唯一默认行为变化是统一原图几何边界检查，包括人物从旧的严格边界排除改为保留点/线接触。square 仍需显式参数，默认权重、置信度、类别、HUD 排除规则及竹子裁边恢复均未更换。
- square 能改善当前新高关数据的可见域指标，但旧集有明确退步，不能据此替换默认模型或声称无伤。

## 改动

### 原图包络

新增 `quad_intersects_frame(quad, image_shape=(360, 640))`，在有限数值、合法尺寸下对闭合图框 `[0,width] × [0,height]` 判定：

1. 任意真实顶点落入闭合图框，直接保留。
2. AABB 与图框严格分离，直接拒绝；等于边界不拒绝。
3. 其他情况对图框两轴及 OBB 四条边的法线执行分离轴判定。统一缩放坐标后投影，避免极大有限包络的投影溢出；只有严格分离才拒绝。

`decode(..., image_shape=(360, 640))` 先通过已有 `physical_quad` 恢复真实几何，再统一判断，之后才执行原 HUD 规则。箭的训练宽带不能代替真实短边参与可见域判断。所有部分相交框保留完整原几何，不裁剪输出，不按类别设例外。非有限及形状不合法的四角继续拒绝。

完整取图调用传入实际 `bgr.shape[:2]`。人物 ROI 重查先以原 crop 的真实边界拒绝完全画外候选，再平移到全图并执行完整解码；不能把 crop 的 padding 假人物平移为合法全图人物。原裁边竹子长度恢复及 HUD 规则继续由原测试保护。

### 显式预处理配置

- `ObbDetector(..., *, rect=None)`：默认 `None` 不向 SDK 增加 `rect` 参数，保留此前 SDK 默认行为；显式 `False` 使用 square，显式 `True` 使用矩形 padding。
- `make_perception(weights, *, obb_rect=None)`：仅在显式传值时向 OBB 检测器转发。非 OBB 权重传该参数明确拒绝；非布尔值在加载模型前拒绝。
- 同一选项用于完整图、人物 ROI 和各自预热，未改 `arena/vision-detector.json`。本次未自行新增用户选项，也未改变 runner 的默认选择。
- 主任务在本次冻结后另加 `center_refiner=None` 可选入口及运行日志，属于独立飞竹圆心接入；见[独立圆心模块](2026-11-16-arena-reticle-center.md)。

## 候选回归及已知退步

以下来自同一批固定原图，比较原 main21 与 main40 的验证前 FP32 EMA＋square 候选。危险物指标统一先保留原 HUD 规则，再按真实旋转包络与原图正面积相交计入可见域；完整原始输出和完全图外数量另存，没有按类别删框。离线计分的正面积口径与本次 actor 保守保留点/线接触需区分。

| 固定数据 | 帧数 | main21 可见域精度 / 召回 | main40 square 可见域精度 / 召回 |
|---|---:|---:|---:|
| 新高关 | 1206 | 69.80% / 61.51% | 95.05% / 94.67% |
| dense | 677 | 96.52% / 81.30% | 95.55% / 81.85% |
| clean | 284 | 98.89% / 82.04% | 98.04% / 81.78% |
| legacy | 6304 | 96.62% / 92.61% | 95.21% / 92.79% |

新高关的 main40 默认 rect 可见域精度 / 召回为 50.74% / 94.23%。square 的 2982 个原始假 `muppet_bomb` 全部在原图外；dense、clean、legacy 分别有 647、286、10551 个，同样全部在外。这是保留原始输出后观察到的位置分布，不是类别过滤条件。新高关 square 的未剔除图外输出口径仍只有约 59.89% 精度，原始失败没有删除。

必须保留的旧集退步：dense 飞竹实体匹配从 213/286 降至 201/286，clean 从 119/145 降至 110/145；clean 锁定提示从 595/635 降至 588/635。人物匹配 dense 625→623、clean 224→221、legacy 6079→6076；绳中心线匹配 dense 976→975、legacy 7081→7075。局部类别变化不能被总体召回掩盖。

候选权重：`debug/arena-client/yolo/finetune/fit-crow-obb-v40-precision-control/weights/epoch1-preval-ema-fp32.pt`，SHA256 `68357516850d1a775698cda922e9a83be1a9ddb163502f74a0a0617c10752944`。它实际只训练至第 1 轮；不将已拒绝的 main39、后续归零的标准 last 或其原生结果混入。

四套原始输出及评分位于 `debug/arena-client/yolo/finetune/main40-padding-{high,dense,clean,legacy}/`；统一汇总为 `debug/arena-client/yolo/finetune/recognition-audit-v37/main40-square-visible-regression.json`。这些离线识别成绩不等于原生闭环完成，更不等于无伤。

## 验证

新增 `tests/test_arena_obb_frame.py`，覆盖斜框与 AABB 重叠但真实分离、负坐标、部分相交、巨大包住画面、无顶点在画面内的横跨框、点/线接触、非有限数值、各类统一过滤、恢复箭真实宽度、原 HUD 顺序、显式图像尺寸、构造/工厂默认行为和 ROI 先检查后平移。

```bash
PYTHONPATH=debug/arena-client/vision-v1/python:tools:agent OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python -m pytest tests/test_arena_obb_frame.py \
  tests/test_arena_obb_detector.py tests/test_arena_detector_factory.py \
  tests/test_arena_bamboo_visual_adapter.py tests/test_arena_obb_operating_point.py -q
```

结果：49 项通过，约 0.14 秒，`git diff --check` 通过。全部为 CPU；没有以此冒充真实 YOLO/原生运行。主任务后续接圆心入口后另跑 118 项聚合 CPU 测试通过，证据归其接入记录。

快速路径微基准仅量化新增 predicate，1000 批/组，不含原解码、YOLO 或设备时间：

| 框分布 / 数量 | 中位 ms | P95 ms | 最大 ms |
|---|---:|---:|---:|
| 普通图内 / 20 | 0.0142 | 0.0180 | 0.2135 |
| 普通图内 / 150 | 0.1059 | 0.1596 | 0.3136 |
| 80% 图内、10% 图外、10% 需 SAT 的跨边框 / 20 | 0.0693 | 0.1133 | 0.4211 |
| 同上 / 150 | 0.5259 | 0.8232 | 1.6131 |

微基准及当时源码 SHA 位于 `debug/arena-client/yolo/finetune/recognition-audit-v37/obb-frame-microbench.json`。其中 detector SHA 是加圆心入口前的边界冻结版本，不能拿来证明后续完整 actor 源码一致。

## 冻结与未完成

边界代码和测试交给主任务审阅后冻结，本分工没有自行提交、切换默认模型、启动训练或操作实例。主任务已启动 14 板首轮原生验证，首轮显式 main21＋phase18、圆心关闭、rect 默认；运行中不能修改 actor 源码。本记录完成时尚无该轮最终结果，也尚无 main40＋square 当前 actor 的完整原生验收。

后续按主任务冻结的源码清单核对原生结果；square 候选需要真实闭环与旧集退步联合判断，不能只因高级关识别指标上升就替换默认。默认 v15／原配置在本次任务中保持不变。
