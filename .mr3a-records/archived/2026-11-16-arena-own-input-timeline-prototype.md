# 自己的按键时间队列：CPU原型与观测/预测游标隔离

## 现象与需求

独立时间码已确认FastCapture返回时刻和画面内容时刻不同，且活动条件下内容龄期随分组变化，不能直接采用固定45ms。现有 `commit_action` 在ACK后立即调用 `Perception.action`，改写active_motion/jump_count；稍后收到一张内容早于按键的图，即使将时间回溯，`max(0, stamp-started)` 仍会把它当作已经开始新动作。

需要先拆分：真实图像所处时刻的感知状态，以及根据自己的已发按键推演到当前/未来的状态。原版物理常量和动作模型继续复用，native物理字段与时间码不能进入正式策略。本轮仅被授权在ignored研究目录做独立原型，运行器/设备/GPU保持冻结；未接入actor。

## 原型改动

文件位于 `debug/arena-client/yolo/finetune/rope-recovery-v37/frame-age-probe/`：

- `own_input_timeline.py`：`OwnInputTimeline`、不可变`OwnInput`和只含动作字段的`ActionCursor`。
- `test_own_input_timeline.py`：23项CPU构造时序/原动作回归检查。
- `own-input-timeline-plan.md`：前期接口及15类测试设计。
- `own-input-timeline-verification.json`：本轮源码SHA、构造三按键重放结果、测试数量和CPU耗时证据。

`record`只接受本机ACK入队戳、物理键、所选primitive与先前像素规划目标，保留既有enqueue+1/60输入先验，可由调用者显式给出同语义先验；**没有设置新的图像龄期补偿值**。事件冻结，目标按允许的像素几何字段序列化；caller修改旧字典或读取出的副本不会改变历史，native/health/model/track对象不写入事件。

`before_observe(image_stamp)` 在观测处理开始前，按估计consumption和提交顺序消费截止该图时刻的事件。动作计算直接复用原 `Perception.action`，位置推进直接复用原 `advance_player/create_motion`路径，不复制YOLO、CUDA模型或tracker。真实游标只保存动作字段，`project(target_stamp)`复制该小游标，并依次重放尚未进入图像的已发按键；连续CRC相同可以重复project，不能重复消费事件或再次发键。

真实与预测接触分开：原 `advance_player` 的普通jump分支即使predict_contact=False也可能预测落地并清跳数，因此原型在真实游标路径保留已用跳数和未确认转换，不把外推当新落地证据；预测副本可显式请求predict_contact=True。若新的物理键处在预测落地但尚无新图确认的区间，保存原primitive和contact_unconfirmed，真实跳数不因该假定清零。普通身体/支撑的真实观测仍由原 `_finish` 判断。

ACK时失去有限rope目标的air_up和反向air_down继续走原primitive/support_unconfirmed路径，不伪装二跳或丢键。旧落地帧可以清掉其图像时刻的跳数；随后重放已经发出的jump，当前预测仍为一跳/二跳，不会被旧帧抹掉。

## 缺框前段与未完成接线

源码复核发现 `ObbPerception.observe` 缺框时直接用 `self.last_observation` 调用 `missing_role_prediction`。因此仅更新active_motion还不够，但也不能把这个真实旧观测直接替换成假新图。原型增加 `missing_role_context()`，在prepared observation期间给出已经重放至image_stamp的预测副本，保留source_image_stamp及player_predicted标记，真实last_observation不动。CPU测试已验证平直静止相机、两个按键之间无新图的缺框预测上下文。

**移动相机情况下该接口暂明确返回 `camera_reference_requires_adapter`。** 原识别器随后还会加完整camera-reference位移；若前段支撑外推已经移动过部分几何，再直接复用它就可能双算。该分支需要单独把参考坐标变换接清并测量，不能只把函数塞入正式Obb观察流程后声称完成。当前运行器没有导入此原型，也没有应用这个拒绝条件；原生跑板行为不受影响。

新图时间必须严格递增，重复CRC走project；image_time倒退或ACK顺序倒退明确报错，不用epsilon伪造差分速度。capture_return与image_stamp分别保存。观察器中途异常会标记本研究游标失败，保留事件，要求在明确episode边界reset；不会在不明状态下自动清队列继续预测。

## 验证

CPU测试覆盖旧帧早于按键、两个/三个事件之间没有图、重复CRC重复外推、落地旧图与后发jump、预测接触不能清真实账本、同戳事件顺序、air_up/反转失绳、真实地面恢复、滑行carry前置消费、零龄期与原ACK动作字段一致、无事件短轨迹与原函数一致、事件不可变/字段过滤、时间倒退、缺框不确认接触、episode reset、异常观察失败边界、显式缺框上下文和移动相机拒绝。

23项新测试通过；连同既有时间码/活动wrapper/动态图评分测试共 **39项通过**，Python编译通过。构造的jump→air_down→air_up三事件无图重放，500次CPU project中位0.095ms、P95 0.116ms、最大3.943ms；真实游标保持不变、consumed仍0。此仅为简单CPU构造用例，不代表高级板帧耗时上限或策略延迟实测。

本轮没有操作任何实例、没有使用GPU、没有读native状态参与原型，也没有修改运行器、动作常量、检测权重或用户配置。尚未做完整动态YOLO+时间队列离线回放、移动相机适配、actor整合与原生对照。此记录不是无伤验收；后续需先review这些接口和边界再决定接线。
