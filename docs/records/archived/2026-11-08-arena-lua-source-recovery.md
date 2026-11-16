# 客户端Lua源码恢复

## 需求 / 原因

继续原版环境还原，需要核对热更新覆盖及Lua敌人/技能逻辑。此前从磁盘猜测AES密钥没有验证，不能当作已恢复。运行时原生库现已可分析，应按真实加载链定位材料。

## 调查与改动

LuaManager.CustomLoaderMethod实际调用TextAsset.get_bytes→Util.DecryptBytesFromBytesAes→CommonUtil.Decompress。只读核对已确认官服进程的LuaManager类型信息、静态字段与Byte[]，Key32字节、IV16字节；不注入/暂停/输入，不读账号配置，不打印材料。原始材料以0600存放忽略目录raw/lua-runtime-key与lua-runtime-iv，本次进程地址未写进通用工具。早先两个候选文件仍未获验证，明确禁止误用。

新增tools/arena_lua.py，输入已导出的原始加密*.lua.txt资产及显式key/iv文件，按AES-CBC/PKCS7/GZip恢复源码，校验长度、GZip CRC和UTF-8，限制解压大小、拒绝冲突覆盖，输出密文/明文SHA256和错误清单；不执行脚本。原始源码和材料不入库。

## 验证

真实导出4813份Lua全部成功，47929363字节，0错误。结果debug/arena-client/lua-recovered/recovery.json；工具重跑与早先探针结果相同。合成密文测试覆盖中文及原始换行字节、非法材料/长度/填充、非GZip/CRC失败、解压限制、冲突拒绝和无输入；与原资源/恢复工具共26项通过。未操作main或安装系统依赖，只在独立工具venv补齐测试依赖。

## 后续 / 未完成

已能读取技能、敌人、热更、配置调用、PUGC板显示逻辑。LazyImport/ddata源码说明NCONFIG由原生diskdata模块读取；不能将4813份源码恢复声称为NCONFIG数据库解密或全部行为移植完成。竞技场生成、板子承载/碰撞、完整角色运动与原版渲染仍继续；Unity许可证等待不阻碍这些工作。
