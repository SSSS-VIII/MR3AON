from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger


@AgentServer.custom_action("ApplyTreasureMapConfig")
class ApplyTreasureMapConfig(CustomAction):
    """
    读取藏宝图配置节点（藏宝图品质 / 藏宝图属性）的 attach 字段，
    动态修改目标 OCR 节点的 expected。

    目标节点：
      - 藏宝图下层识别到目标藏宝图  →  品质 + 属性 组合
      - 藏宝图上层识别到目标藏宝图  →  同上
      - 藏宝图检查品质             →  仅品质
      - 藏宝图检查类型             →  仅属性
    """

    ALL_ATTRIBUTES = ["云之国", "海之国", "神炎国", "雷王山"]
    ALL_QUALITIES = ["神品", "绝品", "珍品", "凡品"]

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        # ── 读取配置 ──────────────────────────────────────────
        quality = "神品"
        attribute = "全部属性"

        quality_node = context.get_node_data("藏宝图品质")
        if quality_node is not None:
            quality = quality_node.get("attach", {}).get("quality", "神品")

        attribute_node = context.get_node_data("藏宝图属性")
        if attribute_node is not None:
            attribute = attribute_node.get("attach", {}).get("attribute", "全部属性")

        # 兜底：非法值回退默认
        if quality not in self.ALL_QUALITIES:
            logger.warning(f"藏宝图配置: 非法品质值 {quality!r}，回退为 神品")
            quality = "神品"

        is_all_attr = attribute == "全部属性"
        if not is_all_attr and attribute not in self.ALL_ATTRIBUTES:
            logger.warning(f"藏宝图配置: 非法属性值 {attribute!r}，回退为 全部属性")
            attribute = "全部属性"
            is_all_attr = True

        # ── 计算 expected ─────────────────────────────────────
        # 1) 藏宝图检查品质：仅品质
        check_quality_expected = [quality]

        # 2) 藏宝图检查类型：仅属性
        check_type_expected = self.ALL_ATTRIBUTES if is_all_attr else [attribute]

        # 3) 藏宝图下层/上层识别到目标藏宝图：品质 + 属性组合
        if is_all_attr:
            # 全部属性 → 正则 {quality}.* 匹配品质后跟任意属性
            map_expected = [f"{quality}.*"]
        else:
            # 指定属性 → 精确匹配 {quality}{attribute}
            map_expected = [f"{quality}{attribute}"]

        # ── 应用 override ─────────────────────────────────────
        override = {
            "藏宝图检查品质": {
                "recognition": {"param": {"expected": check_quality_expected}}
            },
            "藏宝图检查类型": {
                "recognition": {"param": {"expected": check_type_expected}}
            },
            "藏宝图下层识别到目标藏宝图": {
                "recognition": {"param": {"expected": map_expected}}
            },
            "藏宝图上层识别到目标藏宝图": {
                "recognition": {"param": {"expected": map_expected}}
            },
        }

        if not context.override_pipeline(override):
            logger.error("ApplyTreasureMapConfig: override_pipeline 失败")
            return CustomAction.RunResult(success=False)

        logger.debug(
            f"藏宝图配置已应用: 品质={quality}, 属性={attribute}, "
            f"品质expected={check_quality_expected}, "
            f"属性expected={check_type_expected}, "
            f"地图expected={map_expected}"
        )
        return CustomAction.RunResult(success=True)
