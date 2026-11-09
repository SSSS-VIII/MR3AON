# 全对象配对采集当前交接

## 2026-11-10最新状态（以下旧段落为当时快照）

首轮108项已结束：99采样/9准备死亡、21333帧；直接69+派生153目录70，59资源有危险物正标签，详见[全批结果](2026-11-10-arena-full-coverage-capture.md)。OBB纯视觉接口、旋转碰撞、共享物理类别均已提交；原159类目录不是已全部训练。4/12px支撑带同图对照及自身按键回放完成，宽带状态89.31%，未实机。完整7059训练/6972验证原帧的标准模型正freeze0/24epoch训练（session57116），16个只train新种子补采正占用arena（session54358）；不要并发设备查询。旧v4默认仍保留。

后续须按实际原生layout补零样本（香蕉在已记录train种子block3而不是源group1），合并补采、完成验证/独立测试、实机跑图及默认66回归；结束恢复arena首板5000血暂停、visionEvalEnabled=false。见current-work顶部最新记录，不能把下面“未实现/正在评分”的旧快照当现状。

## 稳定检查点

默认八类YOLO v4及三板无伤66检查点保留，不能称全竞技场稳定。41ca002配对连接/两个渲染边界、16395f7原小块/部件归属、21c1bda长板窗口、c3be3bd原对象缓存生命周期、36f2d15浮台/数据探索均已分功能提交。没有改原陷阱AI或碰撞，原K/S/P/5000血/选关菜单保持。

## 有限补采执行器

工具arena_collect_coverage.py按原计划逐窗口、train/val/test独立种子串行采集，可用相同参数续跑。任务、各次失败、死亡、实际可见类型/资源/Collider归属和各分集帧数均落盘；summary同时给planned和completed，不能把complete采样回合误认为无伤通过或已覆盖其请求类型。只允许已知RecycleAllMainAirGround准备故障使用现有run-arena重启一次，租约冲突/标签错误不自动重启。

计划v5为32个缺项窗口+4个使用完整schema4重采的基础类别窗口，共108个独立种子回合；Gale原69类型及未知226/238/257均保留。先12回合2747帧、19个实际家族、无准备失败，源码已有4项纯离线执行器/审计测试及真实续跑。199项arena回归通过/2依赖跳过（后续新增OBB评分测试待下次总验）。

当前完整批采仍在运行：tools/arena_collect_coverage.py，输出debug/arena-client/yolo/finetune/coverage-v6，base_seed21000，计划native-coverage-plan-v5.json。首次limit12日志coverage-v6.log，后续完整续跑日志coverage-v6-resume.log，运行进程由工具session6281等待；只读其主机manifest/summary/log查看进展，禁止同时启动另一arena设备查询抢租约。数据回合会死亡，原样保留。

## 正在验证的标准YOLO OBB

新增arena_yolo_obb_data.py / score.py，以原资源+物理形状+原飞行阶段定义159个类别（69原家族，类别目录不是159类已训练）；使用真正旋转Box四角和Sphere/Capsule平面投影，分别标绳/地面/浮台/可见无碰撞cue。水果原Collider在layer17，不能只用layer9过滤，按原Enemy tag保留层信息。未完整带支撑的旧schema3不当作绳/浮台负样本混入。

首批前三窗口训练547帧、验证576帧，约13个实际训练家族；标准Ultralytics YOLO26n-OBB原模型，加载已微调v4兼容参数696/792，不自写网络/Trainer/loss。12epoch约97.24秒完成，fit-obb-pilot/weights/best.pt，目录profile.json。官方OBB基座SHA6f51c78197aacda4a33be77294065a9001675fb893f56227a179731b53dbd2b0，100空白图推理中位8.16/P9512.59ms，仅基座格式/开销检查，不能当完整实时延迟。

pilot验证总mAP50约0.656、P0.662/R0.692；未达到部署要求，默认未替换。独立test前三窗口正在score-obb-pilot-independent验收（工具session4223）；训练进程session38199可能已结束尚待收结果。原八类v4在新飞镖验证117帧仅85/325召回26.15%、P39.72%，是诊断补数据依据，不是新OBB不同口径的直接对照。

## 未完成

- 完成108回合，按真正训练分集缺项再补种子；死亡过早缺Banana等类别时不能用验证/测试替代训练。
- 完善OBB数据/评分测试与记录，再提交；arena_yolo_finetune.py新增可选transfer，尚待训练工具功能收口。data-obb-probe初版错误地把layer17水果当cue，仅诊断不训练；data-obb-pilot已按Enemy tag修正。
- 基础绳/蜘蛛/乌鸦/弹球完整schema4重采在计划最后四窗口，训练下一版需一起纳入。
- 尚未写新OBB视觉控制适配器/旋转轨迹/旋转碰撞搜索；不能把pilot检测验收当作接入或跑图通过。后续可以复用原Tracking/MPC，但要保留原几何，不能把Box旋转框再变回内接椭圆。
- 数据探索器是有原生标签的采样助手，部署策略不得读取这些原生标签/关卡ID；当前旧视觉入口仍只看像素。
- 结束前恢复arena首板5000血暂停菜单，关闭visionEvalEnabled；不要动main/用户暂存常驻任务JSON。当前批采占着arena，先等其结束。
