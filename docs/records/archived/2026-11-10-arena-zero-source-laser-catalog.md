# 零类型原生激光子弹目录与监督

## 现象与原因

合并补采时，可见未绑定保护在v7/train-w09/frame35拦下family_type_id=0的EnemyBullutLaserAlarm / EnemyBullutLaser。旧工具只收正ID，因此原69+153目录仍漏掉此派生对象；合并在训练前已失败，没有把它当背景训练。

## 改动与原资源核对

完整原APK索引定位9c9c015e6f807e760b19a33017ae1b08.ab中的enemybullutlaseralarm.prefab，使用现有只读当前资源提取链导出14包依赖、0错误/Patch1248一致。Cfg中相似名字6050指向EnemyBulletLaserAlarmBT，不能猜为同一物，因此没有把它硬配到6050。

runtime_catalog对原生0类型按精确Prefab根名记录，使用原Prefab脚本再核对。已有Bamboo零类型继续归原Bamboo族；新激光用独立runtime_enemies资源族，不造整数EnemyType，也不建立全局type_bindings[0]。schema保留其原Box及脚本/依赖；object_resource仍须根名+原脚本同时匹配。原EnemyInfo/BaseProperty当前参数保存在配对增量引用中。

## 验证与后续

新增保护证明不同0类型不能被误绑定，原型无伪造ID；目录/数据18项通过。新合并完整构造成功：**11810训练/6972验证、71资源族、69资源有危险物正标签**，无可见未绑定目标。标准13类模型保持同一官方结构，正在继续6epoch微调；尚未替换默认或宣称新权重实机。

另纠正V9手工期望ID填错：岩虎131、荆棘106（木偶炸弹实际200），更正写入coverage-v9/expected-type-correction.json并保留原计划SHA。采集生成只用map/board/sample，标签始终来自原生ID，未使用手填期望改生成/标注；后续罕见类验收计划全部从profile反查ID。

训练回访已得到香蕉428、木偶炸弹128个原对象帧；荆棘从更早block10采到345对象帧，角色随后死去原样保留，不能称通关。岩虎较早入口仍未见目标。另在新种子做香蕉/炸弹、荆棘、激光父机关的val/test采集，不混入训练。
