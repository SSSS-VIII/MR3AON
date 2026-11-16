# 竞技场原始 GPU 程序恢复

## 需求与原因

用户要求原版模型、特效与碰撞环境供视觉训练。此前 UnityPy 默认 Shader 导出只检查旧 `m_SubPrograms`，本客户端实际使用 `m_PlayerSubPrograms`，因此不能据旧导出认定客户端不含 GPU 程序。代码段与参数段共用目录，也不能把所有目录项都解释为程序。

## 改动

增加 `tools/arena_shader_programs.py`：只遍历真实玩家程序引用，解析分平台/分段 LZ4 目录，保存原始程序字节、GPU 代码和变体绑定结构；拆分最外层 VERTEX/FRAGMENT 宏，保留嵌套预处理与表达式。原资产与生成结果仍位于忽略目录，未提交客户端源码/密钥。

同时导出竞技场已定位实体的 427 包闭包；对序列化宽高和像素长度均为零的运行时字体纹理，明确登记预览缺失，不伪造像素，不丢弃原始组件。

## 验证与边界

- 232 Shader / 2595 程序 / 5190 阶段恢复，0 错误。
- 5190 阶段的 ESSL310 派生副本全部通过 glslang 语法检查。部分原 ESSL300 使用显式 uniform location，检查副本将版本提升为 310；原字节未修改，此结果不代表原 300 代码原样通过，也不代表 Unity 渲染等价。
- 原 Spine4.0.21 小黑皮肤1/run 使用恢复出的 Spine/Skeleton 程序，在 Mesa 实际编译并渲染成功，截图位于 `debug/arena-client/spine-probe/original-shader-preview.png`。该独立宿主适配属性名、矩阵上传及 packed color alpha，并非原 Unity 完整渲染管线，不能作为像素等价验收。
- 427 包导出 0 错误，唯一明确缺少预览的是原始零尺寸 Font Texture；含 342 ParticleSystem、87 BoxCollider、46 SphereCollider、6 CapsuleCollider 等原始组件。导出不代表组件已驱动运行。
- Shader/资源恢复/Lua/diskdata/客户端相关 32 项测试通过。完整可操作训练环境尚未完成，继续核实原客户端 GameOnly 离线入口及平台承载。
