# 原版上翻途中下翻与平绳适用限制

## 需求与原因

落绳恢复已支持下翻途中上翻，但原版也允许上翻途中再次下翻。之前决策层`can_air_down`仅允许jump/air状态，没有将原state4纳入；直接给它套跳跃下翻28速度也不正确。用户要求持续改进原动作预测，保持跳数与支撑确认可靠。

本次先交叉核对原生反汇编与原UI采样，再增加该反转。原速度门使用`GroundCollider.PointStart.y`；可见斜绳局部高度无法替代原段起点，因此新增反转保守限制在可确认平直绳上，不能宣称已完成斜绳反转模型。

## 原版依据

- `ProcessMovementOnLine`在`49d6ad0`分派state4；`49d7d94`读取本帧down字段`Ninja+0x102`，`49d7db0`调用`EnterRollToLineDown`。若`GetGroundYIncludeAir`的out平台非空，还受`get_WaitToSlide`（`+0x34d`）的门控，不能泛化为所有地面/浮台均可取消。
- `EnterRollToLineDown`从`NinjaInfo+0x54`取8并设state3；只有原`IsInAirWhenEnterRollToLineDown`成立时才从`+0x58`取28。helper本体比较根Y是否高于原GroundCollider.PointStart.y＋foot＋静态offset。
- 原只读字段实测`InAirOffsetWhenEnterRollToLineDown=5`、`isEnterRollToLineDownReviseVelocityFlag=true`；两个相关原热更槽均为空。证据在`rope-recovery-v37/reverse-source-fields.json`、`reverse-hotfix-fields.json`。
- 普通跳跃下翻并不经过该helper。`ProcessMovementOnLine 49d6578–49d6624`对physics14/15/16/17等直接跳到`49d6628`；`49d6630`读取`NinjaInfo+0x58`，取负写velocity.y，`49d6670`切state3。因此普通跳跃在高度不足5.75时仍使用28，与反转默认8并不矛盾。摘录保存于`reverse-down-followup/native-jump-down-bypass.txt`。

## 原UI采样与延迟

主任务使用原按钮输入采得5组，原物理与伤害均未修改，全部采样HP5000：

| 原样本 | 最后down前状态 | 初始根Y | 输入后约0.1秒根Y | 用途 |
| --- | --- | ---: | ---: | --- |
| rope_low_reverse | state4 | -0.395821 | -0.624180 | 低处上翻反转 |
| rope_mid_reverse | state4 | 0.137402 | -0.197403 | 中段上翻反转 |
| rope_top_reverse | state4 | 0.564178 | 0.235821 | 接近绳上反转 |
| double_roundtrip | state4 | 1.884766 | 0.302588 | 空中28下降中的上翻再反转为8 |
| single_roundtrip | state1 | 0.750000 | 0.182110 | 已恢复绳上后的普通下翻对照 |

前4组是真正反转，最后1组不能冒充state4反转。原物理50Hz、呈现60Hz，输入之后可继续呈现前动作一段时间。按前动作延续计算lead，再进入8下降，采用有效呈现延迟35ms；配置保留25–45ms范围。该范围是离散帧/插值校准边界，不是统计置信区间，也不是新的截图延迟或游戏全局延迟。4组在约0.1秒处的预测误差均在0.12世界单位以内（尺度40时约4.8像素），不是整条轨迹精确重放或策略无伤证明。

原始样本、静态字段、热更槽和每份SHA均保留在ignored目录；`vision-motion-priors.json`引用7份原证据摘要。较高位置走28的反转分支有原代码依据与参数化测试，但本轮4组有效实测反转实际均为8，不能把它们当成新反转28分支的实机验收。

## 改动

- `arena_motion`让air_down携带自身speed/input_delay，时长、轨迹和待确认运动统一使用。未指定参数的普通跳跃下翻仍为原28/既有延迟。
- 新`can_reverse_rope_up`只接受active为rope_up/air_up、phase为flip_up、目标为rope、没有地面/浮台上下文且当前有限绳可见的场景。MPC已有`can_air_down`候选入口，因此直接获得反向下翻候选，不增加用户选项。
- 平绳检查同时查看选中`rope_segment`与`rope_segments`中的所有可见片段；任何可见坡段都拒绝新增反转，避免一小段平线掩盖原绳段有坡。端点仅容许不超过1像素且斜率不超过1%的测量噪声；这是保守的视觉判据，不是原游戏坡度参数。没有segment数据的旧标量平绳路径保留兼容。普通跳跃下翻的坡段路径不受这个新门控影响。
- 反转lead沿前动作推算，选择8/28时考虑输入延迟期间的原运动；保留已用跳数，实际普通身体落绳后才清零。预测接触与真实接触继续分开。
- ACK重定时越过绳端时，保留已发送的air_down primitive和发送前自己的像素目标，标记support_unconfirmed，不丢输入或虚构已落绳；随后只有真实普通身体与可见绳/地面接触才结束未确认状态。
- 关联修复：固定rope_up超过预计时长但尚未观察到接触时，保持flip_up，避免之前误写成flip_down而让下一动作语义相反。

## 验证与未完成

新增测试覆盖原8/28分支、普通跳跃下翻不变、4组原UI数值、速度/延迟统一、跳数恢复、有限绳端、ACK保留动作、实际地面恢复，以及选中斜绳、其它可见片段斜绳、只有rope_segments时的斜绳均拒绝新增反转。旧标量平绳和微小端点噪声可用，普通跳跃在斜绳仍能下翻。

本功能20项测试、连同落绳/绳端专项50项通过；当前完整工作区arena回归483通过，Crypto与UnityPy两项因宿主缺依赖跳过。`git diff --check`通过。完整工作区同时含其它在研功能，该总数不表示本功能单独新增483项。

本次只做源码与CPU回归，没有操作设备、GPU或main，也没有修改原游戏物理、伤害、输入机制和训练权重。斜绳反转明确仍待原段起点/根位机制校准；新增反转的整板策略效果等待主任务冻结源码后的独立实测，不将HP5000动作采样记作自动跑图无伤。

### 冻结后同图反事实

对前一版`native-fork-v39`四回合的150个flip_up完整视觉观测，以实际历史输入ACK时间分别用冻结旧源码及本版重算。84帧可列出新增air_down选项，其中13帧从等待改选air_down，另7帧只改变等待原因、均不发键。回放路径`rope-recovery-v37/replay-reverse-v40.py`及两份`reverse-counterfactual-before/after.json`可复算。这证明新增动作实际进入候选搜索；后续帧仍沿用旧操作历史，不能当作连续轨迹或减少伤害的证明。

### 四板原生闭环（reverse-v40）

随后主任务用冻结本版代码、原main21＋phase18权重，在原arena实例复测前轮相同的四组种子。`native-reverse-v40`四回合源码清单的27份SHA均与运行前`reverse-v40-sources`封存文件一致；训练/GPU评分未并跑。回合全部完成，外层session50811退出0，最终恢复1101/5000血/原暂停、菜单键盘可用且eval关闭。

| 板号 / seed | 前轮v39损血 | 本轮v40损血 | 实际新增反向下翻次数 |
| --- | ---: | ---: | ---: |
| 61081 / 39203 | 480 | 480 | 0 |
| 61081 / 40200 | 0 | 480 | 6 |
| 51043 / 40201 | 400 | 0 | 3 |
| 6011 / 40202 | 480 | 0 | 3 |

新动作12次均由原按键提交为air_down，两个此前有伤回合本次无伤；但61081/40200由无伤变有伤，因此仅能确认动作进入闭环并能按原机制运行，不能宣称整体稳定改善或全板无伤。相同seed并不使实时截图/按键轨迹相同，变化也包含MPC未来候选对当前选择的影响，不能把全部伤害差都归因某一次反转。

capture→Unity按键P95分别84.23/76.03/70.59/90.67ms，最大125.54ms；首回合存在该长尾，不能只给P95而称全部按键小于100ms。新39203在11.85秒原runOnLineDown状态受480；当时下一上翻原回执比原伤害晚约10ms，正在单独核查之前动作/危险范围，未把它写成已解决。
