# 原客户端视觉训练reset/step接口

## 需求与原因

原模型/碰撞/随机地图环境打通后，需要让视觉模型按原物理步与图像交互，不能仅提供人工键盘或把原内部数据混进纯视觉观测。此功能接续 [原客户端离线入口](2026-11-09-arena-native-offline-environment.md)，不包含模型训练或自动跑竞技场策略。

## 改动

新增tools/arena_env.py，使用LocalClient/InstanceSession("arena")，已有环境复用，未启动时可自动调用本机run-arena --paused --no-focus。reset(seed,chapter,level)返回原1280×720 PNG和单独的状态；step(none/jump/down或0/1/2,ticks=1..600)返回图像、原_scoreInfo._totalScore差值、死亡标记及实际步数/轨迹。没有增加手工奖励；state/layout属于可选标注，不应输入纯视觉策略。单步原操作按下持续至首个原物理步后释放，二段跳需另一次jump。

每次step结束暂停；死亡后禁止继续step，必须reset；reset失败也关闭旧回合，避免把错误复位后的图像接进上个episode。截图直接来自Session.screenshot；close只暂停，保留arena与资源。Observation.save保存PNG及JSON至调用者目录。README给出可直接运行的Python用例与字段说明。

## 验证

在stop→冷启动后的全新原游戏进程中实际通过Python接口：

- seed42/章节1/第4段reset后HP100，PNG头验证尺寸1280×720。
- jump30步实际30物理/36渲染，原分差356.94446563720703，HP100，最终fall。
- down8步实际8物理/9渲染，原分差95.92294692993164，HP100，最终rollToLineDown。
- 再reset(seed42,level4)，原最终布局与首次逐项一致，90块；reset(seed43,level4)布局改变，91块。
- 先前实际死亡试验已验证第397物理步HP0提前返回、reset后HP100；见入口记录。对应截图、状态及布局仅留在忽略目录gameonly/final-training-api、death-reset。

适配器7项离线回归覆盖原分数差、实际步数、提前死亡、死亡后禁止step/允许reset、失败复位关闭旧回合、非法动作/步数不下发命令。相关提取/恢复/配置/Shader/控制/显示/适配器合计48项通过；补充失败reset守卫后7项适配器回归再次通过。Python编译、shell语法与git diff --check通过。

边界：同种子只实证最终地图一致，不宣称开场插值或VFX逐像素确定；实际reset会经历原开场，episodeFrame初值非固定0。依托本机原运行时及已提取专有资源，并非可公开分发的独立Unity工程；普通竞技场基础小黑以外未逐一验收。未操作main，原有常驻任务暂存改动保持独立。
