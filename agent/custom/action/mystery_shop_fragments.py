import re

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger


# 商店卡面是「流派·忍者碎片」。空格会先被节点 replace 去掉。
FRAGMENT_ROSTER = [
    "双焰·小椒",
    "星闪·小椒",
    "神炎·小椒",
    "炎魂·小黑",
    "龙焰·小黑",
    "冰羽·兮兰",
    "寒绡·兮兰",
    "瞬翎·伊鹤",
    "霜刃·伊鹤",
    "奔雷·银枭",
    "雷羿·银枭",
    "超威·阿力",
    "雷兽·阿力",
    "绯斩·苍牙",
    "鬼狩·苍牙",
    "神乐·琳",
    "雪舞·琳",
    "不知火·舞",
    "剑心·卫鲤",
    "夜叉·隼白",
    "月晖·小夜",
    "樱火·荧",
    "猫太·老板娘",
    "鬼斩·紫原",
    "龙吟·洛青",
    "风铭·戌时",
    "极刃·血影",
]

CONFIG_NODE = "勾玉购买忍者碎片配置"
SLOT_COUNT = 8


def fragment_pattern(name: str) -> str:
    return re.escape(name) + r".*碎片"


@AgentServer.custom_action("ApplyMysteryShopFragmentConfig")
class ApplyMysteryShopFragmentConfig(CustomAction):
    """
    读取勾玉购买忍者碎片配置的 attach，把勾选的全名写入八个商品位的碎片识别。

    attach 的 key 是流派·忍者全名，值为 true 才购买。
    多个勾选靠配置合并进同一个 attach，和藏宝图一样。
    没有勾选时商品位保持关闭，商店继续只买忍币商品。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        del argv
        config_node = context.get_node_data(CONFIG_NODE)
        attach = config_node.get("attach", {}) if config_node else {}
        roster = set(FRAGMENT_ROSTER)
        selected = [name for name in FRAGMENT_ROSTER if attach.get(name)]
        for key, value in attach.items():
            if value and key not in roster:
                logger.warning(f"无法识别的勾玉碎片 {key!r}，已跳过")

        if not selected:
            logger.info("未勾选勾玉忍者碎片")
            return CustomAction.RunResult(success=True)

        expected = [fragment_pattern(name) for name in selected]
        override = {
            f"神秘商店商品{index}是配置碎片": {
                "enabled": True,
                "recognition": {"param": {"expected": expected}},
            }
            for index in range(SLOT_COUNT)
        }
        if not context.override_pipeline(override):
            logger.error("勾玉碎片 override_pipeline 失败")
            return CustomAction.RunResult(success=False)

        logger.info(f"勾玉碎片: {selected}")
        return CustomAction.RunResult(success=True)
