# 原箭家族监督与只读运动参数

## 需求、原因与原版依据

新第5/6关回归仍有大量箭伤。当前19类v13把原EnemyArrow与其他Box陷阱合并，不能可靠启用箭专属运动模型。原资源绑定213→EnemyArrow脚本/BoxCollider；214→EnemyArrowWarning且没有物理碰撞，不能把警告图形当伤害区。

原EnemyArrow.StateLogic反汇编确认active/stay/fly/onGround状态；vy -= gravity*deltaTime*3.5，vx += velocityAccX*deltaTime*3.5；arrowType/isAimNinjaX另有分支。ShootIntoGround检查尖端/深度与当前地面，UpdateCollider入地后移动/缩短子碰撞。上述是源码依据，不是部署时读取敌人状态的授权。

## 改动

vision_labels的既有只读controller字段增加_arrowType、_velocityX/Y、_gravity、_velocityAccX、_activeDistance、_rotateZ、_deepInGround、_currGroundY、_aimPos、_isAimNinjaX、_ninjaPos、_offsetPos、cameraVx及警告显示参数。只用于采样/标注，不进入actor。

schema/build可显式启用arrow_family；必须核对原EnemyArrow脚本和唯一Box形状，不能按长条外形或未知ID猜类别。标准物理profile在既有19类之后追加arrow（20类），只改变原EnemyArrow物理目标的类别，不修改原quad/裁切/物理所有者规则；警告仍为cue，旧19类顺序保留。默认选项关闭，当前已部署权重仍v13。

## 原生补采和数据验证

用同名arena的InstanceSession/LocalClient/FastCapture，原传送/通灵兽到第6关52/6101，内部sample_block18/23补采，原UI探索跳跃/下翻；无强制root/碰撞/怪物随机改动。34110/34111训练323帧，34112/34113验证323帧，34114/34115独立测试323帧，共969。六组god全部false；sample_block18起始5000，sample_block23在撤去原通灵兽后已受到825伤害，起始4175，不能称任意小块入口天然安全或把采集称无伤跑图。所有原采集作业已结束。

原对象帧均fire:1、gravity25、velocityAccX0，读到active/stay/fly/onGround；训练两回合2556对象帧（非独立箭个体数），不能以重复帧当更多原参数配置，也不能推断其他箭型/地图必定同参数。六组没有EnemyArrowWarning实例，警告参数尚无新增原生实例验证。

合并保持原96回合和新4个train/val回合按整回合分离：14150训练/8134验证，arrow物理正标签1767/825；旧19类v13只有939训练箭、旧验证没有箭正目标，此次补齐独立验证而非只调训练集。旧缺飞竹阶段274/247帧仍显式排除，不当背景。2项新监督保护通过，当前工作区（含未提交运动候选）的343项arena通过/2缺依赖跳过；本监督提交新增2项，不混交候选预测器。

## 未完成

标准Ultralytics YOLO26n-OBB由v13继续20类、freeze0/batch16/seed17、10epoch训练session49759进行中，未替换默认，不能称20类已验收。箭轨迹的直线/标定抛物线/视觉曲线竞争与不确定范围仍在工作区开发，后续独立预测回放、旧资源验证和原生多种子无伤检验完成前不冒称可用。

忽略目录arrow-motion-study-v14保留原反汇编、字段/积分契约、入口layout、生成脚本与训练日志；arrow-coverage-v14保留计划、6个原回合、源快照/参数表/摘要；data-arrow-v14为旧939箭单列的中间数据，正式候选使用data-arrow-expanded-v14。用户已有任务JSON暂存未改。
