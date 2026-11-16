# 动态资源不可读时拒绝旧APK回退

## 现象与原因

扩展地面/绳索资源时，普通用户无法穿过原DynamicContent目录权限。Path.is_file/exists将该权限失败隐藏为False，读取器误用APK旧资源；最初导出的地面依赖与既有动态资源出现同CAB不同内容，不能合并。原客户端资源本身没有缺少这批文件。

## 改动

ClientSource在显式指定动态目录时验证目录可读取；逐包只在FileNotFoundError时回退APK，权限错误继续抛出。版本读取同样不隐藏权限错误。资源导出不再将不可读取的更新内容误认为不存在。

本次只读拷贝白名单中的AssetBundles文件及PatchVersion到私有debug缓存，再按原清单重新导出。没有读取账号配置、复制凭据或操作main设备。旧的terrain-resources及terrain-resources-available属错误来源试验，不能当作当前客户端资源；有效产物为terrain-resources-current，438根包/632依赖包/0导出错误，PatchVersion1248。

## 验证

合成APK测试覆盖正常动态覆盖与真正不存在时回退、显式目录缺失、读取权限失败不回退；相关资源提取测试通过。有效导出与既有arena-entities-complete按对象摘要交叉核对，未混合旧Shader内容。
