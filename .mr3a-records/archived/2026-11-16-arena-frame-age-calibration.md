# 捕获图像内容龄期：暂停、活动、推理负载与动态同帧校准

## 原因与测量方法

v40 飞竹受伤只读分析发现，连续画面修正后人物相对绳的位置比原根位置偏高，等效约45ms的下降位移。这个数字未区分显示内容龄期、原渲染插值和检测中心偏差，不能直接加入策略。背景与角色同步移动也必须消除，不能按屏幕绝对Y误算运动。

因此增加研究目录中的可撤销像素时间码：原 Lua bridge/UGUI 每帧绘制带 nonce、frameCount、CRC 的小码，记录设置/上传/EOF三个时间；FastCapture 只取像素和自己的时间头，结束后再匹配原帧日志。原 `coroutine.step()` 是 WaitForEndOfFrame，探针显式 yield nil→写码→EOF，并核对同帧和 renderedFrameCount。停止只通过 StopCoroutine 取消返回的自身 coroutine handle，销毁自身 UI/纹理并移除探针函数；不改游戏物理或输入。

FrameServer把 `captureDisplay` 返回后的 System.nanoTime 记为device_captured_ns，因此原capture→Unity按键指标未包含缓冲内容在此之前已经存在的龄期。测量保存set/upload/EOF边界；CRC、nonce、set/EOF不一致或负时间均明确作废，不擅自移动帧号。只使用命名arena，main未动。动作偏差的原证据见[reverse-v40动作审计](2026-11-16-arena-reverse-v40-motion-audit.md)。

## 暂停场景实测与独立复核

主任务执行 `frame-age-probe/results/paused-smoke`，session28835退出0，3s共91次采样。实际Unity屏幕1920×1080，捕获640×360，临时UI按参考分辨率缩放，首图已人工查看，原PNG可独立重解码：

- 91/91 nonce/CRC/帧匹配有效，91个不同帧；相邻解码帧89次跨2帧、1次跨1帧，没有重复帧把统计压低。
- 201条原日志的 set frame、EOF frame、renderedFrameCount 均一致。12张保存的原PNG用独立解压后再解码，payload与抓图时记录全部相同。
- captureDisplay返回时间减同码EOF时间：最小24.523ms、中位40.200ms、P95 41.234ms、最大42.468ms。
- 减写码时间的中位为43.124ms；set→EOF中位2.776ms，最大34.316ms。已保留长render间隔，未人为移动帧号抵消它。
- 89/91次截图的码比捕获时已完成EOF的最新帧落后2帧；另两次分别0/1帧。该计数与约40ms的独立时间差一致，但不能仅凭它宣称底层恒定双缓冲。
- 原帧率约59.768fps。条件为 timeScale0/captureFramerate60、640×360、不记录pose、不运行推理。停止后 timeScale和captureFramerate保持原值，场景对象和探针全局均不存在。

这一组 `captureDisplay` 调用本身（device_captured−device_start）中位 **1.588ms**，含readback/传输的请求往返中位 **3.799ms**；相同截图内容相对EOF另有 **40.200ms** 的中位龄期。不能把40ms称为截图服务调用耗时，也不能用3.8ms请求耗时代表整张图的实时程度。活动组调用中位约1.49–2.36ms、请求中位约3.75–4.50ms，内容龄期仍另行计算。

源数据和 SHA 在 ignored `debug/arena-client/yolo/finetune/rope-recovery-v37/frame-age-probe/results/paused-smoke/independent-review.json`，原PNG复核在 `independent-png-check.json`。

## 数据边界

EOF是Unity CPU回调，不能称GPU fence或物理显示时间。此次已核实的是时间码对应内容在捕获时的龄期；游戏画面与该码同帧的姿态对应，仍需要后续同EOF原碰撞框组验证。暂停组 captureFramerate60也不能与原 `MR3A.resume()` 后 captureFramerate0、timeScale1的活动条件混算。本轮尚未更改任何观测延迟补偿，也不构成无伤验收。

## 已准备的活动复测入口

ignored `frame-age-probe/active_retest.py` 在原安全1101开头组织独立轻载、pose、推理组。前四block共72world无敌人，每组最多4s；先完成原选板、捕获服务和marker初始化，再原resume，避免准备耗时让角色提前进入敌人区。finally先原pause，再取回后验日志和卸载marker，最后恢复原暂停菜单/键盘。wrapper不发送跳跃/下翻。

轻载先测30Hz和15Hz；pose组另记同EOF原根/碰撞框。推理组明确读取某个冻结actor setup中的主/阶段权重与profile SHA，先预热再准备游戏，抹掉全部时间码区域后执行像素 perception/MPC，丢弃决策，不把原日志送进策略。安全板负载不能代表高级陷阱密集板最坏情况，报告已标边界。

原解码9项加wrapper顺序/时长/不加载推理的3项，共12项CPU测试通过，Python编译通过。准备时未运行实例；后续由主任务执行，下节如实记录结果。本子任务仅检查本地证据和准备脚本，未操作实例/GPU。运行命令和退出路径见 ignored `frame-age-probe/PLAN.md`，没有加入正式actor或训练数据入口。

## 首批活动结果：严格排除恢复前和边界帧

主任务随后完成两次轻载、一次pose和一次冻结推理组，均使用原 resume（captureFramerate0、timeScale1），5000→5000，停止并恢复菜单成功。最后推理组session69386退出0。本节只读取已完成报告，没有接管设备。

原 resume 在本地桥协程的帧末执行，因此活动集合采用 **`resume.state.frame < marker.frame < pause.frame`**；码等于恢复帧时只列边界，不冒充活动内容。30Hz组第一张码早于resume，15Hz轻载组第一张码等于resume，均剔开。暂停60组不入活动池。

| 条件/原目录 | 所有有效码 | 严格活动码 | EOF龄期中位 / P95 / 最大（ms） | 距捕获时最近已完成EOF的落后帧数 |
| --- | ---: | ---: | --- | --- |
| active-light-30hz | 121 | 120 | 45.969 / 47.788 / 48.161 | 119次2帧，1次3帧 |
| active-light-15hz | 61 | 60 | 28.840 / 30.990 / 31.353 | 60次1帧 |
| active-pose-15hz | 61 | 61 | 36.566 / 39.251 / 40.248 | 56次2帧，5次1帧 |
| active-inference-15hz | 61 | 60 | 41.822 / 43.033 / 43.630 | 60次2帧 |

四组原实际渲染帧率约60.020、60.055、59.923、60.088fps；pose/推理组均无pose_error。推理组另有1张resume前旧码，因此其原始61张统计41.824/P9543.388/max45.464ms不能直接冒充严格活动集合。30/15Hz轻载中，捕获时刻距最近已完成EOF的中位分别12.560/13.697ms，但解码内容落后帧数不同。两组差异不只是简单的“在同一帧内何时截到”；另一方面同15Hz的pose组又得到不同值，所以单次分组不足以将队列/起始相位/额外开销的影响归因给采样频率本身。

两轻载组合并的180张活动码，EOF龄期最小26.520、中位44.926、P95 47.512、最大48.161ms。这个池按观测数加权，30Hz贡献120帧、15Hz贡献60帧，**中位44.926不是普适补偿参数**。加入pose组后的241张描述性池中位39.762ms，更说明随分组权重变化的混合中位不能代表固定链路延迟。

新增 ignored `frame-age-probe/summarize_active.py` 只读已完成目录，按上述边界分类每张码、按原resume帧率条件分池，并保留轻载/pose/inference各组分布。结果写到 `activity-summary.json`，附原输入SHA、分组健康/恢复状态和数据边界，现已包含四组。它不导入运行器、设备、模型或GPU，未改actor延迟模型。

推理组完成后再执行汇总：四组共301张严格活动码，描述性加权池中位41.807/P9547.357/max48.161ms，轻载/pose/推理原分布仍单独保留。冻结main21/phase18推理链自身用时中位31.723/P9542.100ms；安全1101无高级密集陷阱，该负载不是正式最坏情况，不计算为演员的跑板成绩。

对推理组同一码的EOF原Role平面框与记录的当前感知框做后验比对：60张绳上普通姿态，中心绝对误差X中位0.069/P950.319px、Y中位0.118/P950.382px，宽度绝对误差中位1.756px、高度0.595px。结果在 `active-inference-15hz/same-frame-pose-review.json`。这里只验证稳定绳上姿态；动态翻转、跳跃和可能缺检时的预测代替尚未被该组覆盖，不能推及v40动态偏差。

## 动态pose＋时间码组：准备与执行边界

已准备 ignored `frame-age-probe/dynamic_retest.py` 与 `dynamic_sequence.lua`，由主任务审查后执行，本次不自行连接实例或GPU。沿用安全1101、先初始化服务/marker、within-cap原resume；保持原captureFramerate0，每帧EOF记录原root和Role平面。

固定计划在resume后约0.20s下翻、0.70s跳键回绳上、1.20s一跳、1.45s空中下翻、1.55s上翻、2.15s再下翻，全部调用原 `GameOperate.OnLeftDown/OnRightDown` 与对应Released，hold60ms。意图名称只是计划，必须以之后真实EOF物理状态核验实际动作；不写native位置、速度或状态flags。记录每次call/return monotonic、frame、原Time.time及释放日志。正常/异常均释放两键，仅停自身coroutine、删除自身对象、原pause及菜单恢复；4.25s另有自停保护，若提前自停，统计用最早原pause帧排除尾部暂停码。

4s捕获最多160帧，所有原RGBA先存内存，结束暂停并清理后才压PNG，约141MiB的最坏原帧内存量。图片均标calibration-only并排除训练；后续GPU空窗可对遮掉全部时间码区域的原图离线运行main21，用同码EOF几何比较，分离内容龄期和动态检测误差。准备阶段未跑动态组，也没有依据静态结果写入35/45ms补偿；随后实测和后验核对结果见下节。

动态wrapper新增2项CPU边界保护，和既有12项共14通过；Python编译及Lua5.4/LuaJIT5.1语法加载通过。以上是执行前的准备验证，Unity原UI调用组合的实际结果另列如下。


## 动态组实测：六次原UI动作、同帧几何与额外龄期

主任务执行 `results/dynamic-pose-30hz`，session77859退出0。121/121 nonce/CRC/同帧有效，121张原PNG全部保存；其中第一张码等于resume帧452117，只算边界，**120张严格活动图**。原暂停边界452361，实际约59.981fps，captureFramerate0/timeScale1，5000→5000，error/cleanup_error均空，原菜单恢复成功。该组安全1101没有危险物，不计作任何高级板无伤成绩。

严格活动EOF龄期最小23.728ms、中位 **27.494ms**、P95 **29.192ms**、最大29.800ms；120张码都比捕获时最近已完成EOF落后1帧。写码龄期中位31.954ms，set→EOF中位4.303ms。捕获调用本身中位1.611ms，请求往返中位4.636ms，仍与内容龄期分别计量。原始121张含边界的中位27.460ms不能直接替换严格活动统计。同为30Hz的前次轻载组中位45.969ms，进一步否定直接部署固定45ms。

实际原UI时刻相对resume/start为0.213、0.701、1.201、1.468、1.550、2.166秒，六次意图依次为rope_down、rope_up、jump1、air_down、air_up、rope_down，均找到之后真实对应physics：state3、4、jump14、3、4、3。首个新physics EOF距UI返回约17.0–36.5ms，包含原输入/渲染离散，不能冒充精确consumption延迟。

本组air_up在452211–452212仅维持2个原渲染帧，452213已恢复state1与普通身体，rootY仍为0.8727，之后收敛至0.75。再次证明不能用固定转换时长或严格root==0.75替代视觉普通身体/支撑确认。活动码按原physics分布为绳上33、下翻16、绳下56、上翻7、jump8。

CPU只读脚本 `analyze_dynamic_native.py` 输出 `dynamic-native-review.json`，记录事件、状态切换、按状态分组龄期及相机/世界根运动分离。空中下翻三张图（index45–47）从时间码对应EOF到捕获时最近完成EOF，原根已下移约18.48–18.50px；这几张共同相机位移约0。它是离散EOF比较，不虚构捕获时刻的插值真值，但已能说明：仅一帧旧内容在高速下翻期间也会产生十几像素位置差，不能全部归咎于检测。

## main21原始全帧检测：先保存像素结果，再做同码EOF评分

主任务另执行 `compare_dynamic_player.py`，session70006退出0。输入只为保存的121张PNG，全部时间码区域先抹去；固定main21权重SHA `aaca8d956dbdf688fff0076bfbe34378e9d57a7b3f4ff6bf0008a140723b78ee` 与profile SHA `1c51f27e54cd7f0da5f5cb058e71e13a0450608f95ae710257e0a5f8e6443d4c`。只用原标准YOLO全帧输出、既有像素lane关联，不加载阶段模型，不用ROI fallback或运动预测代替player框。`main21-raw-player.jsonl` 完整关闭后才打开native几何评分，模型未接触原标签。

120张严格活动图中111张有raw player框、9张无框。有框时中心绝对误差Y中位0.134px、P95 2.020px、最大 **2.474px**；X中位0.108px、P95 1.883px、最大8.281px。这只验证本次1101姿态序列，不能泛化到高级关复杂前景或重叠陷阱。

| 原physics | 活动图 | 原始全帧有框 / 缺框 | 有框中心Y绝对误差P95（px） |
| --- | ---: | ---: | ---: |
| 绳上state1 | 33 | 33 / 0 | 0.591 |
| 下翻state3 | 16 | 9 / 7 | 2.313 |
| 绳下state2 | 56 | 55 / 1 | 2.020 |
| 上翻state4 | 7 | 6 / 1 | 2.474 |
| jump14 | 8 | 8 / 0 | 1.406 |

CPU逐图人工核对留下 `dynamic-player-misses-review.png`（绿为同帧原Role框，红为raw检测）。7张下翻缺检index8/9/11/67/68/70/72和1张上翻缺检index22的原Role框均约 **7.90×7.90px**；前3张没有金币闪光仍缺检，后4张另叠金币/闪光。index101为普通绳下身体被黑色前景遮挡。最大X误差index17/18为−7.751/−8.281px，均处于普通绳下被大块深色前景遮挡，框置信仅0.377/0.426；不能用它们修正全局root位置或原运动常量。

**这9张只是禁用ROI的原始全帧缺框，不是实际actor缺9帧。** 正式 `ObbDetector.detect` 已有局部ROI fallback，`ObbPerception`还会对短缺口做受限动作外推，必须单独验证。已准备 `compare_dynamic_player_roi.py` 沿用原detect+ROI、仍禁native选择，输出与原始全帧分离；准备时仅CPU编译/--help通过；随后原版ROI复放已由主任务执行，结果见本节补充。期间主任务独占GPU进行14板原生首轮，本子任务没有操作实例/GPU或改runtime。

新增两项CPU保护验证精确nonce/frame关联、PNG/捕获码不一致拒绝、resume/pause边界排除和有符号几何误差。与原探针14项合计 **16通过**；模型推理由主任务实际执行，CPU单测不冒充模型或无伤验收。

## 旧像素与自己的已发按键：时间队列设计，尚未实施

源码核对发现 `commit_action` 立即更新 `Perception.active_motion/jump_count`，后来的旧内容即使stamp早于动作开始，也会因 `max(0, stamp-started)` 被套上新phase。单纯给图像时间减常量会扩大此因果错误；必须先把真实图像时刻的感知状态与当前时刻的动作预测分开。

详细接口和15项测试设计保存在 ignored `frame-age-probe/own-input-timeline-plan.md`：ACK只入不可变own-input队列；观测开始前只消费截止image_time的事件；规划副本按时间顺序重放观测之后已发送的键，不能重新发键或修改真实感知账本。真实旧落地帧可重置旧时刻跳数，但重放随后已发jump之后，当前预测跳数必须仍为1/2。air_up和反向下翻的primitive/失支撑不确定目标继续保留。不能deepcopy CUDA模型/整个tracker，也不能将规划落地写成视觉确认。

观测队列必须放在 `ObbPerception.observe` 最开头，早于缺检外推及slide偏移支撑查询；只放在 `_finish` 前不足。保留capture_return与image_time两个字段，避免把runner的fresh_intervals和请求耗时混入backdate。年龄估计若变化造成image_time倒退，需要显式拒绝/快照重放，不能用epsilon制造差分速度。native码/原root/物理状态始终只在事后评分中使用。

上述仅为设计与独立校准证据，未接入演员、未设置固定27/35/45ms补偿，未改变任何正式输入或物理参数。父任务原14板测试期间运行源保持冻结。


## 原版ROI fallback复放补充：九次尝试均未补上

主任务随后执行 `compare_dynamic_player_roi.py`，session47516退出0。仍是相同121张原图、固定main21权重/profile、同样抹除时间码、像素结果全部保存后再读native。120张严格活动图中source为 **111 full_frame、9 missing、0 local_roi**；9个缺框索引与上一套逐一相同，111个有框的坐标和后验误差也逐项相同。原ROI尝试均实际运行，9次耗时最小5.525ms、中位5.870ms、最大7.545ms，不能将零补框误说成没有走fallback。

两套结果及CPU交叉检查分别在 `main21-roi-same-frame-review.json`、`main21-roi-manifest.json`、`main21-roi-independent-review.json`。这说明原240×240局部窗口/imgsz320路径在本组未弥补小翻转姿态及遮挡缺口，后续需要独立研究窗口/尺度与可见性。当前仍未执行完整actor的运动缺框外推评分，所以 **9次检测器缺框仍不等于9次actor完全无角色状态**。未为本case临时改检测阈值、裁剪尺度或正式策略；原生多板测试源继续冻结。
