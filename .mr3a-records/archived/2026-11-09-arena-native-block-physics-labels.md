# 长板小块定点采集及原生物理标签

## 需求与原因

仅从整块版型开头采14秒，7007/7006/7008实际先看到Paw2/BlueSpider/MuppetBomb，不能覆盖这些长板后部引用的其它机关。复合电球父对象原标签还会合并子EnemyBase的Collider，造成重复巨大目标；只导出AABB也不足以复核旋转机关。

## 改动

内部native_select增加可选sample_block（非菜单选项），按原StageStartX+目标数据点X−第0块数据点X定位，复用原通灵兽120速度、落地、回收额外buff和等原保护到期；完整地图/前序事件保留。默认nil行为不变，超出已生成块继续等原生成，越过目标板会报错。

vision_labels升级schema3：源类型及父/家族，Collider与Renderer按最近EnemyBase归属；Collider完整TRS、Sphere/Capsule/Box参数和Box四角；相机矩阵、原生LevelBlockCollider端点/绳地/隐藏及切换状态；当前支撑id及块索引。控制器白名单字段保留原运动状态，派生直线飞行类型单列motion_family。纯粒子仅在没有普通主体且粒子数量>0时回退，非凭粒子预制体存在就标可见。

collector保存真实生成布局、native_travel、所加载源码及摘要，使用已验证配对连接；准备预算620秒覆盖原生跳关600秒上限，不再用原90秒超时打断较远目标。

## 验证

LuaJIT原选择/坐标换算及协议、板池和标签相关29通过/1环境cv2缺失跳过；后续全套回归另列。原同版型实景103/108起点分别落在目标小块X后0.146/0.202单位，之前“可能四倍越过小块”的怀疑未成立，不改固定40的原结束距离。

新schema3/同步版pool-probe112：7008第8小块附近135帧8.03原秒，初始5000/god=false，结束2195.8；原探索动作受伤如实保留。可见对象帧目标按家族237=1081、238=398，Sphere=1091、Box=388；绳/平台支撑均有实景，全部Collider.owner_id与对象一致。复合体子对象源0沿实际父层级归家族，不把它们冒称额外资源种类。setup记录目标X8032.80、骑乘结束8005.16、脚下支撑仍属块7，随后已达到目标X；不宣称一定脚下索引等于选择索引，端点附近由原支撑接管决定。

238虽无当前Cfg条目，实景能生成EnemyRotateElectricBall；修正目录说明，226/257未验证。旧schema2的103含重复合并仅诊断，不用于下一轮训练。

独立复现112还定位重置异常：重开前_airMainGroundList已有1个null SpriteRenderer，原RecycleAllMainAirGround直接遍历解引用导致失败，非回收顺序调换。原PUGCManager.RecycleLevel反汇编已核对现顺序。此提交没有吞异常或修改陷阱，继续追踪null入池来源；后续批采恢复只能使用现有arena重启，main未动。全资源覆盖/下一版权重尚未完成。
