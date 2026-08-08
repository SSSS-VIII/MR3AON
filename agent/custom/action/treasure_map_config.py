from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger


@AgentServer.custom_action("ApplyTreasureMapConfig")
class ApplyTreasureMapConfig(CustomAction):
    """
    读取藏宝图配置节点 attach 字段（由 UI checkbox 合并写入），
    动态修改第一层 OCR 节点的 expected，实现品质+属性组合过滤。

    attach key 格式: "{品质}{属性}"，如 "神品云之国"、"珍品海之国"。
    多个 checkbox 勾选会通过 dict merge 合并到同一个 attach 中。

    目标节点:
      - 藏宝图上层识别到目标藏宝图  →  品质+属性 组合 regex
      - 藏宝图下层识别到目标藏宝图  →  同上
    """

    QUALITIES = ["神品", "绝品", "珍品", "凡品"]
    ATTRIBUTES = ["云之国", "海之国", "神炎国", "雷王山"]

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        # ── 读取配置 ──────────────────────────────────────────
        config_node = context.get_node_data("藏宝图配置节点")
        attach = config_node.get("attach", {}) if config_node else {}

        if not attach:
            logger.info("未选择藏宝图，任务结束")
            return CustomAction.RunResult(success=False)

        # ── 从 attach key 解析品质+属性组合 ───────────────────
        map_expected = []
        parsed = []
        for key in attach:
            # key 格式: "{品质}{属性}"，如 "神品云之国"
            matched_quality = None
            matched_attr = None
            for q in self.QUALITIES:
                if key.startswith(q):
                    matched_quality = q
                    matched_attr = key[len(q) :]
                    break
            if matched_quality and matched_attr in self.ATTRIBUTES:
                parsed.append((matched_quality, matched_attr))
            else:
                logger.warning(f"藏宝图配置: 无法解析 attach key {key!r}，已跳过")

        if not parsed:
            logger.error("藏宝图配置: attach 中无有效的品质+属性组合")
            return CustomAction.RunResult(success=False)

        # ── 按品质→属性排序，保证顺序稳定 ──────────────────────
        parsed.sort(
            key=lambda x: (
                self.QUALITIES.index(x[0]),
                self.ATTRIBUTES.index(x[1]),
            )
        )
        map_expected = [f"{q}{a}" for q, a in parsed]

        # ── 应用 override ─────────────────────────────────────
        override = {
            "藏宝图上层识别到目标藏宝图": {
                "recognition": {"param": {"expected": map_expected}}
            },
            "藏宝图下层识别到目标藏宝图": {
                "recognition": {"param": {"expected": map_expected}}
            },
        }

        if not context.override_pipeline(override):
            logger.error("ApplyTreasureMapConfig: override_pipeline 失败")
            return CustomAction.RunResult(success=False)

        logger.info(f"藏宝图已选择: {len(parsed)} 个组合, " f"{map_expected}")
        return CustomAction.RunResult(success=True)
