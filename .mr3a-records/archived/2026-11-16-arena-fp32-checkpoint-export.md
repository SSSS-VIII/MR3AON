# 标准 YOLO 微调另存无损 FP32 EMA

## 现象与原因

高级关数据追加后的 main39 使用标准 YOLO26n-OBB / Trainer，但保存的 best 检查点出现大量浮动平台假检。第1轮 live val mAP50=.89108，磁盘模型在高级关1,206帧却给出78,703个假浮动平台。原碰撞监督、20类profile与support12未变化，不能通过删类别或遮掉底边修复。

同源、同数据、同超参、同seed40150重做第1轮受控实验，声明原3轮调度并以官方callback停止，保存验证前/后完整FP32 EMA及同epoch标准FP16检查点。结果：

- live metrics与main39第1轮一致；验证前后所有浮点state的SHA相同，当前Validator没有原地half污染EMA。
- 完整FP32 EMA有110个BN方差超过65504，最大2,740,721。标准Trainer保存时 `deepcopy(ema).half()` 后 `nan_to_num_`，将它们截成65504。
- 同16张原图、同官方GPU FP16预测路径：标准FP16文件输出2,141目标，其中1,168个假浮动平台；验证前/后FP32文件均输出123目标、0假浮动平台。stock PyTorchBackend先融合FP32 BN再转推理half，因而FP32文件保留了必要数值。
- CPU FP32推理也能复现被截断文件的假检；只在加载后转float无法补回已丢失的方差。

本机Ultralytics8.4.208的Trainer、Validator、torch_utils、tasks和PyTorchBackend五个文件均匹配已安装wheel的RECORD，未改包源码。该检查不等于重新下载官方包或独立签名验证。第2、3轮live val归零仍是另一未解释问题，不能仅用磁盘保存失真解释。

证据位于 `debug/arena-client/yolo/finetune/fit-crow-obb-v40-precision-control/paired-epoch1.json`、`recognition-audit-v37/main40-paired-probe.json` 和 `installed-sdk-record-audit.json`。控制脚本在最终验证的重复 `on_fit_epoch_end` 回调上触发停止断言，session2581 exit1；训练、三产物和最终标准验证已结束，CPU补全元数据与重载检查，未重训、未改权重，详见 `completion-note.json`。研究停止回调已改为幂等。

## 改动

新增 `tools/arena_yolo_checkpoint.py`，仅使用公开callback入口，不替换Trainer/网络或标准保存路径：

1. `on_train_epoch_end` 独立复制验证前FP32 EMA，不改live模型或其train/eval标志。拒绝已降精度或NaN/Inf的浮点state；不把坏值截断成有限值。
2. `on_model_save` 审计验证后state，记录前后SHA是否相同；按标准validation fitness另存 `weights/best-fp32.pt`，保留原架构、class/profile、metrics、文件SHA、各tensor精度与FP16越界计数。逐epoch审计和best审计独立保存。较差epoch或非法state不能覆盖已有合格文件。
3. `arena_yolo_finetune.py` 安装这两个官方callback，完成时返回FP32 best及其审计位置，同时保留原标准best路径。默认推理模型、原客户端、actor均未修改。

这里的“best”仍只表示标准训练指标选择，**不是检测品质或无伤验收**。验证前后state若发生变化会在审计中明确标记；导出的验证前快照可保留调查，不能把相应post-validation指标无条件解释为它的成绩。

## 验证与边界

- 5项真实CPU PyTorch序列化回归：超过FP16范围的BN值原样保留、live模式不变、拒绝NaN/Inf和已half的state、较差fitness或非法post-state不替换已有文件、验证前快照与变化审计、官方callback注册与跨epoch快照拒绝。
- 原support监督迁移保护3项通过，`py_compile`、`git diff --check`通过。
- 用实际main40完整FP32 YOLO模型运行helper并用官方YOLO重载；所有浮点state SHA相同，110个越界值保留。该smoke只在CPU保存/加载，没有训练或设备操作。通用helper尚未跑新一轮完整训练。
- main40完整四套固定评分已完成，但它仍被拒绝为actor：高级关/dense/clean/legacy物理精度分别 .5073/.8813/.9511/.6782，main21为 .6980/.9652/.9889/.9661。FP32解决了上述保存失真，却仍有底边muppet_bomb假检和少量角色/支撑召回退步；没有因此更换默认模型。

后续将以同一FP32权重比较官方rect最小padding和训练式square预处理，并核对冻结层的BN状态；不通过过滤muppet或底边修补，不在GPU窗口未分配时训练。数据与其余识别研究记录见 [冲刺识别复核](2026-11-15-arena-crow-recognition-audit.md)。
