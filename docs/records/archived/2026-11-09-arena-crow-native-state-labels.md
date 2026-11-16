# 原生乌鸦状态、碰撞缩放与配对标注

## 需求与排查结果

缩短所有操作锁至0.18秒的实跑受伤480，仅在站立状态放开锁的版本690；对已确认低置信目标进行短时保留的版本720，都比已提交版本差，均撤回，产物保留于finetune/native-timing48、rope-timing48、confirmed48。不能将“动作更快/目标保留更久”当成已改善。

随后直接读取原EnemyStraightBat预制体和真实运行对象，只作离线核对。原生状态为enterScreen、stay、ready、rushToNinja；等待/预备阶段世界速度+14，匹配角色滚动，屏幕近乎静止；冲刺世界速度-10，当前镜头相对约-948px/s。ready计时0.3秒。31个原生单tick配对帧还确认：冲刺动画将子物体X缩放从1.2增至1.56，Unity SphereCollider按最大轴缩放，因此真实球体范围也增大约30%，并非纯美术拉伸。原贴图本身的颜色变化不能只靠SpriteRenderer.color推断，后者在该序列始终为白色。

预制体/运行字段分别在crow-prefab-fields.json、crow-live25.json；原动作序列在crow-sequence25/。资源查询一次误用ReleaseAsset接口失败，后续按已有预览代码使用handler:Release；初次引用的显式释放未确认，最终收尾应重启arena客户端清理该诊断引用，不影响main。

## 改动

`vision_labels.lua`在原碰撞/可见标签之外输出原EnemyBase.dead及乌鸦的状态、状态计时、停留时间、冲刺距离、动画枚举。全部仅用于标注和验收，不进入实时策略。收集器允许指定原生板位池，避免为了收集第二块而改地图结构；仍复用同一arena租约和原advance。

## 验证

三段独立原回合states50、states52、states51各468帧、28.02秒，包含随机原生跳跃/下翻，固定原池1101→11022→11032。标签中的dead为正常JSON bool，controller状态为原枚举字符串，ready与rush均有独立样本。三段结束均暂停并恢复菜单，无main操作。收集无模型推理、无碰撞改动。

后续八类标准YOLO适配正在独立目录训练；未替换已验证的六类默认权重。其数据/模型验收另记，不将原状态元数据直接喂给运行策略。
