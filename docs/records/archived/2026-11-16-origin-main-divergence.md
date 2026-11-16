# main推送分歧：合入远端自动兑换码提交

## 现象与原因

用户在回main后推送提示远端分歧。上次整理仅核对了本地缓存的origin/main=d456070，没有fetch，因此当时显示ahead而未发现远端已有新提交，这是检查遗漏，并非main快进丢失或改写了提交。

本次git fetch origin取得1265924。main与origin/main分歧为本地342、远端3；共同祖先d456070。远端独有fca4651（10月26日）、a198a0c（11月2日）、1265924（11月9日），均为github-actions[bot]的chore: update weekly codes，净变化只有assets/remote/game-meta.json中的每周兑换码。

## 处理

在main执行git merge --no-ff --no-commit origin/main，自动合并成功，无冲突。兑换码从本地「禅语魔心逆袭悬赏活动来袭」更新为远端「三千日答谢礼11月12日签到领取」；其它元数据保持。以常规双父merge提交保留远端自动提交与本地全部功能记录，不rebase、不force push。未推送，未操作游戏或运行实例。

## 验证

核对暂存差异仅兑换码、本次归档与交接一段；JSON可解析、diff检查通过。合并后origin/main为main祖先，远端独有提交数归零，可按正常快进推送。原工作区未完成研究和任务配置仍保留，不混入合并提交。该验证针对本次fetch所得远端，远端后续若再有提交仍需先合入。
