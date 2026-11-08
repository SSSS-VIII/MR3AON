# 竞技场运行时元数据、原生方法定位与编辑器安装

## 需求 / 原因

继续恢复竞技场真实行为，避免用参数或空脚本代替状态机。磁盘global-metadata及libil2cpp仍有保护，仅导出AssetBundle不能得到行为。用户确认没有Unity编辑器或现成工程。

## 调查方法与结果

本轮仅对已确认官服进程的宿主`/proc`映射作只读读取，核验cmdline为官服包名且cgroup为既有waydroid。没有ptrace附加、暂停、注入、hook、输入、账号配置读取或Android重启。地址只对应本次进程，不能写进工具当作跨会话固定地址。

1. 在匿名映射中定位与已知元数据表头一致的内容，读得23963956字节完整运行时元数据。SHA256：f1d16cb21e3b85b202c2e3a231bc6c5f18302d831bba00c86bc95fe913ab6910。运行时头magic=0/version=24；实际按公开v31布局解释时header=256、MethodDefinition=36、TypeDefinition=88，能一致解析21672类型、185158方法。此为结构推断，不擅自把保护头覆盖成标准文件后宣称已通过官方解析器。
2. 按实际ARM64库各映射及文件偏移重建本地分析副本124311728字节（未写回运行进程），运行库可见磁盘保护版本不可见的Assembly-CSharp.dll模块名。SHA256：08cc44d9d8c8edf397fa886335ffd04897ab1b8ab1d3ddd44c4ba788afa0d9b0。运行时重定位指针需减去本次基址，不能拿磁盘加密库的空结果判断无代码。
3. 解析模块方法指针表并与元数据token匹配，74模块共173736个可映射原生方法；Ninja、NinjaCollider、ItemAirGround共678个。Capstone读取到正常ARM64指令；通过已映射UnityEngine方法名核对调用目标。
4. ItemAirGround.FixedUpdateMovement相对地址0x48849e8，MyUpdate=0x4884ca8，ResetItemInfo=0x4887314；NinjaCollider.ChangeColliderState(NinjaAnimState)=0x4a3a590。原生方法中保留xLua hotfix优先分派，不能忽略覆盖层。按指令实际指针链读取（全局指针→metadata usage→class→static_fields→delegate）确认本次两个方法槽为空；这只说明检查当时走原生后备分支，不代表整局或其它方法一直无热更。

所有中间原件、地址表、探针、反汇编和参数签名均在忽略目录`debug/arena-client/decoded/`及`debug/arena-client/probe_*.py`。当前探针带本次地址、仅供分析，尚未作为通用功能提交。

## 已核实行为线索

ItemAirGround.FixedUpdateMovement调用UnityEngine.Time.get_fixedDeltaTime（目标0x6b484d8），不是任意渲染帧delta。移动分支按fixedDeltaTime减少剩余时间、以两轴速度乘时间改变位置；开始移动前还判断角色位置、方向和距离。完整坐标意义、初始信息、回收及角色承载尚待核实，不能只拿speedX/Y做永久直线运动。

NinjaCollider两个ChangeColliderState签名分别是Boolean和NinjaAnimState，不能因同名误配。运行时FieldInfo表已确认字段偏移：normal radius/height=0x28/0x2c、roll radius/height=0x30/0x34、jump height=0x38、roll/slide/normal/jump center=0x3c/0x48/0x54/0x60、主CapsuleCollider=0x80。

动画枚举常量通过压缩整型默认值解码（与已安装Unity的`utils/MemoryRead.cpp`核对），不是直接读取int32。NinjaAnimState：jump=3、roll2=8、attack_charge=18。0x4a3a590原生分支对jump设置jump center和jump height，对roll2设置roll center和roll radius/height，对attack_charge设置slide center且radius/height均取normal radius，其它状态设置normal center/height/radius。还受坐骑Collider已启用等前置条件保护。结合本体prefab，局部setter参数为：

| 分支 | center | radius | height |
| --- | --- | --- | --- |
| 普通 | (0.1,0,0) | 0.2 | 1.8 |
| jump | (0.1,0.3,0) | 保持前态（普通配置0.2） | 1.2 |
| roll2 | (0.05,0,0) | 0.1 | 0.1 |
| attack_charge | (0.05,-0.3,0) | 0.2 | 0.2 |

此处只核实setter代码与prefab配置，未验证Unity/PhysX对height<2radius的形状处理、根运行缩放、触发器关系或真实接触边缘。jump分支只设置center/height，并未强制恢复radius，不能假设从任意上一状态进入都得到0.2。

Ninja.UpdateGravity、Jump、EnterJump/EnterJump2、翻绳入口已提取带调用目标名称的反汇编；完整物理更新顺序、输入门和动态速度仍未移植或标定。没有将这些线索写成几何原型的假精确实现。

## 编辑器安装与验证

从Unity中国官方归档提取2022.3.62f2c1 changeset=92e6e6be66dc，下载官方LinuxEditorInstaller/Unity.tar.xz，4152241040字节；下载SHA256：b0c6ad5ac2996ed7863c3628dd6a546f1fd9749102226b3e2feaa2d2da24883b。安装在`/home/linn/Unity/Hub/Editor/2022.3.62f2c1/Editor/Unity`，`-version`实际返回2022.3.62f2c1。

batchmode启动明确失败：No ULF license found、Token not found in cache、No valid Unity Editor license found。没有代用户登录或激活。已向用户发出登录Hub并激活适用许可证的异步提示；编辑器授权相关操作等待用户完成，不据等待时间视为授权。

Unity Hub已下载并启动GUI入口；不要将Hub附带PlasticSCM path异常或headless无法选择历史版本解释为编辑器安装成功，本次安装成功依据独立安装包解压和实际版本输出。Java补装引起的既有离线系统更新失效仍未恢复，具体备份与影响见 [资源恢复记录](2026-11-08-arena-original-resource-recovery.md)，已向用户告知，未升级或重启系统。

## 验证范围与未完成

验证限本机实际元数据、方法token/地址关联、ARM64指令、Unity方法调用、压缩枚举值及字段偏移交叉核对。没有生成完整C#行为工程，没有通过编辑器运行验收，也没有实机轨迹或碰撞逐帧比较。随机板子行为、角色全部状态、着色器及特效恢复继续开发中。此调查不增加新的单元测试，带固定进程地址的探针不作为可复用实现提交。
