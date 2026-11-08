# 官服竞技场客户端资源提取

## 需求

用户要求从 Waydroid 官服客户端提取竞技场关卡、跳跃/下翻和速度参数，为本地模拟器及后续自动竞技场脚本准备数据；随后明确第一版以小黑基础动作为准，并要求拿到资源后直接制作可操作的本地模拟器。本文记录已完成的资源读取，模拟器另按功能收口。

## 来源与排查

- 按记录、历史和代码交叉检查命名实例与现有竞技场流水线；当前流水线处理入口、结算、问答等，没有完整跑酷物理模型。
- `InstanceSession` 确认 main 运行且控制租约被现有脚本占用；未显式接管。xiaoli 的只读包列表确认是 OPPO，small 保持停止。main 官服包为 `com.pandadastudio.ninjamustdie3`。
- 从 main 宿主数据根 `~/.local/share/waydroid/data` 只读访问实际安装 APK 和外部 DynamicContent。热更新 PatchVersion 是长度前缀字符串 1248，Unity 版本 2022.3.62f2c1。未使用 Downloads 中旧安装包替代实际安装源。
- UnityFS 前置 78 字节重复头和 Unity China 资源加密已解析；资源密钥从该 APK 元数据匹配并用加密签名校验，未输出到记录或提交。NCONFIG 和 Lua 另有处理层，尚未完整解开。
- 临时索引实际读取 APK 9088 包、热更新18134包、额外小包3401条（小包与主索引可能重叠），已记录条目无解析错误；这是有界排查范围，非全客户端扫描完成。目标资源找到后停止本次索引进程。
- 辅助只读检查 Player 数据、元数据常量和限定的运行进程匿名内存 JSON 字段，没有写内存、注入、暂停或向游戏发送输入。检出的 `_gravity=12` 属 EnemyArrowDataStruct，SLIDE_TIME=0.5 属敌方 Ninja，均未当作小黑参数。Unity Physics2D 默认重力也未当作角色参数。

## 改动与结果

- 新增 `tools/arena_client.py`：纯离线读取、同名热更新优先、完整原始 TextAsset bytes、Stage 摘要、Level JSON、组件/碰撞体结构导出、来源摘要；检测读取期间文件和 PatchVersion 变化。密钥不打印，客户端资源只在忽略目录。
- 新增 `tools/arena_nrbf.py`：结构化读取本次 Level 使用的 NRBF 类型、成员、数组、引用、枚举、列表；不运行 .NET 类型或 BinaryFormatter。
- 独立工具依赖记录在 `tools/arena-requirements.txt`，没有改 Agent 环境或定制 MaaPiCli。
- `debug/arena-client/dataset/` 导出 Endless 546 Stage / 44 Level、Endless_Gale 646 / 32、SingleEndlessReserved1 301 / 17，共1493个Stage、93份Level，19168个地形块、112655个敌人放置、100430个物品放置；保留局部坐标、缩放/旋转、自定义障碍数据、随机段权重、难度及原始速度。这些是资源池，非当前服务器必选路线。
- 三包均在当前热更新目录无同名覆盖，实际来源是已安装 APK；摘要保存每包SHA-256和每个TextAsset摘要，不将「APK来源」写成「新热更新内容」。Stage模式编号分别0、6、15，原始速度值约9～20；没有将其当作像素/秒。
- `debug/arena-client/xiaohei/` 导出本体 Role1，包 `f01f901904c917350202578593240b59.ab`，本体脚本为Ninja，排除NinjaCopy，相关Ninja/1 Spine名为nijia_black。Ninja数据：moveSpeed8、normalGravity约-19.8、jumpForce1/2=23.5/12.5、一段上/下重力-25/-9、二段约-9.8/-9.8、地面/空中下翻速度字段8/28。正常Collider配置半径0.2/高1.8，下翻0.1/0.1，跳跃高1.2；已区分主碰撞和坐骑碰撞，保留原始CapsuleCollider、kinematic Rigidbody以及根缩放0.52，未猜测世界碰撞尺寸。
- 完整路径、工具用法与未确认语义见 `docs/develop/竞技场客户端数据.md`。

## 验证与未完成

- 16项针对性测试通过：NRBF前向引用/空值段/类型复用/原始二进制/异常长度、路径边界、热更新优先及克隆/敌方脚本剔除；真实1493 Stage JSON解析、93 Level NRBF导出通过。
- 正式工具从实际 APK 元数据自动匹配资源密钥、解密小黑本体、关联Ninja/Collider/3D物理对象并输出来源摘要通过；main末次状态仍RUNNING。没有点击、启动比赛、重启实例、改任务计划或接管主脚本。
- 配置值已提取，**运行时覆盖、积分规则、时间单位、输入缓冲、下翻持续与切换条件未实机标定**；NCONFIG/Lua没有声称已完整逆向；没有用配置值推导并宣称真实跳高或滞空时间。
- 用户已有暂存的常驻任务JSON调整保留，未混入此功能提交；没有推送。用户追加的可操作本地模拟器继续开发，后续自动竞技场策略尚未接入游戏。
