# 竞技场原版资源闭包恢复与占位工程审计

## 需求

用户要求原版模型、动画、特效、碰撞及随机板子，用于视觉模型训练；确认没有安装Unity、没有现成工程。本次完成原始资源保全及独立小黑骨骼渲染这一阶段，完整训练环境仍未完成。前次原型验收撤回见 [需求纠正](2026-11-08-arena-fidelity-requirements.md)。

## 原因 / 调查

客户端为Unity 2022.3.62f2c1，角色使用Spine；几何替代无法满足训练。清单包含真实循环依赖，不能按无环排序拒绝合法资源。Spine文件名nijia_black_5.25不表示版本，二进制头部实际4.0.21。AssetBundle保存资源和序列化字段，不提供原始IL2CPP/Lua行为源代码。

AssetRipper恢复工程有文件但不可等同还原：23/23个C#为Dummy class，211/211个生成shader含DummyShaderTextExporter；Ninja空类中注明未知脚本后端。UnityPy对Spine/Skeleton导出的1573字节文本不含GPU源码，原Shader二进制另行保全。不能用空C#和声明Shader宣称可运行。

## 改动

- 新增`tools/arena_fidelity_assets.py`，按当前清单解析闭包、允许环、拒绝缺失引用；保留全部原始SerializedFile/resS、对象原始负载、完整type tree、二进制字段、原始TextAsset及纹理解码预览。检查源更新版本、冲突字节；解析失败列明并非零退出。
- 元数据记录包来源及SHA256、所有组件类型、实际Spine头版本、脚本类名和限制；资产解密材料与原件始终只在忽略目录。
- 新增占位工程审计，列出已知dummy脚本/Shader；即使未命中也不判定训练环境已验证。
- 新增6项针对性保护测试与完整操作/验证边界文档`docs/develop/竞技场原版资源恢复.md`。

## 验证

本机官服实际APK/热更新只读导出，PatchVersion为长度前缀1248（原始hex 0431323438），main没有接管、输入、重启或改状态。六根包：f01f901904c917350202578593240b59、f34d7058023b2dd5892cebdd3570e146、ccc594ffc8050a6b867f86481a9b4c60、3b61efefec46ca07b2e0fea14332e4a3、226c45fc0cc73f0ea2572f9ccf6fea3f、ecff2476358ccc1a83b57ead9632c5be（均.ab）。闭包86包，0错误，约43MB。全部类型包括95个Texture2D、231个Shader、105个Material、62套ParticleSystem/Renderer、20个AnimationClip、11个AnimatorController、18个Animator、9个Box/CapsuleCollider以及相机、Mesh等；共享包包含其它角色，不将其算作已复原的小黑效果。

AssetRipper 2.0.0从`fidelity-recovery/serialized`成功生成`restored-unity-project/ExportedProject`，审计确认占位数量。原件、审计及对象索引在`debug/arena-client/fidelity-recovery/`。AssetRipper官方Linux包SHA256为6f5d4352d36795b944243eb3ec790ec37dbca6d6756e52605bc8616e042d384e。

官方Spine Viewer 4.0.64可解析原始skel/atlas和1024×1024纹理。default皮肤只显示骨骼；明确选皮肤1、run动画后，已实际渲染小黑原始贴图动画。解析92段动画，run=0.5s、jump≈0.366667s、roll2≈0.066667s、fall_roll≈0.4s、slide=0.5s。动画长度不是状态持续时间或物理判定。原始纹理和骨骼未改，Java探针、清单和截图均在忽略目录`spine-probe/`，`verified-run.png`为实际窗口截图。查看器SHA256为02f5b2841824c32e74773d13b4c3da7cca935764dbd1edfee7eca6b9c8c98e81。

资源工具16项加新恢复工具6项，共22项通过；覆盖依赖闭包、环、缺失引用、精确保全、冲突拒绝、实际骨骼头版本、占位审计及不能误判完成。没有实机物理、碰撞或画面等价验证。

## 编辑器与环境影响

官方Unity Hub已下载到忽略目录recovery-tools，SHA256为832e3923e036fcc279f2031db88b7193300ca9125a3cf8ba0b04812b1d6ae528；公开下载链接重定向中国版。Linux headless可列版本，但历史版本需changeset；官方中国归档确认2022.3.62f2c1的changeset=92e6e6be66dc、Linux安装包4152241040字节。后续已安装匹配编辑器并验证版本，但授权未通过，见 [运行时调查与安装](2026-11-08-arena-runtime-code-investigation.md)；Hub登录/条款激活未代用户执行。Hub还报PlasticSCMUtil path未定义异常，日志保留。

为骨骼查看器补装java-25-openjdk图形库，同时依赖mkfontscale、ttmkfdir、xorg-x11-fonts-Type1（4包、约2MiB），触发DNF将11月3日准备的1476项离线更新标记失效。没有执行升级或重启。原transaction.json及offline-transaction-state.toml已备份到recovery-tools/offline-update-backup；原缓存仍保留。尝试`--assumeno`离线重放时CLI明确不支持replay的--offline，未变更事务；未篡改rpmdb_cookie绕过一致性检查。已向用户说明实际副作用，截止当前未恢复排队有效性，后续需通过系统更新工具重新解析准备事务；不能声称环境完全无改动。

## 未完成

完整竞技场训练环境、实际状态机/输入/碰撞等价、动态板子运动/生成/回收、镜头、材质/粒子触发及游戏帧对照均未完成。Lua/NCONFIG和受保护IL2CPP行为仍未恢复；资源闭包不包含任意字符串动态加载。Unity编辑器可用也不代表以上代码和视觉缺失已解决。
