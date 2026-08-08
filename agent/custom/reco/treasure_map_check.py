from typing import Optional, Union

from maa.agent.agent_server import AgentServer
from maa.custom_recognition import CustomRecognition
from maa.context import Context
from maa.define import RectType
from maa.pipeline import JRecognitionType, JTemplateMatch
from utils.logger import logger


@AgentServer.custom_recognition("TreasureMapQualityAttributeCheck")
class TreasureMapQualityAttributeCheck(CustomRecognition):
    """
    藏宝图第二层检查：在准备页面校验品质和属性是否同时匹配用户选择的组合。

    读取 藏宝图配置节点.attach 中已选组合（如 {"神品云之国": true}），
    截图一次，分别用 TemplateMatch 在品质 ROI 和属性 ROI 做匹配，
    仅当 (best_quality + best_attribute) 组合在 attach 中存在时才命中。

    这样避免误入：用户选择"珍品海之国"+"凡品云之国"，但误入"珍品云之国"时，
    品质命中"珍品"、属性命中"云之国"，组合"珍品云之国"不在 attach 中，不会命中。
    """

    QUALITIES = ["神品", "绝品", "珍品", "凡品"]
    ATTRIBUTES = ["云之国", "海之国", "神炎国", "雷王山"]

    # ROI 区域
    QUALITY_ROI = [77, 14, 87, 72]
    ATTRIBUTE_ROI = [159, 14, 147, 72]
    THRESHOLD = 0.75

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        try:
            # ── 读取用户配置 ──────────────────────────────────
            config_node = context.get_node_data("藏宝图配置节点")
            attach = config_node.get("attach", {}) if config_node else {}

            if not attach:
                logger.warning("藏宝图品质和属性均符合: attach 为空，无任何组合可选")
                return None

            # ── 截图 ──────────────────────────────────────────
            img = context.tasker.controller.post_screencap().wait().get()

            # ── 品质 TemplateMatch（全部识别，取最高分） ──────────
            best_quality = None
            best_quality_score = 0.0
            for q in self.QUALITIES:
                template_name = f"藏宝图{q}.png"
                try:
                    reco_detail = context.run_recognition_direct(
                        JRecognitionType.TemplateMatch,
                        JTemplateMatch(
                            template=[template_name],
                            roi=self.QUALITY_ROI,
                            threshold=[self.THRESHOLD],
                        ),
                        img,
                    )
                    if reco_detail and reco_detail.hit and reco_detail.best_result:
                        score = reco_detail.best_result.score
                        if score > best_quality_score:
                            best_quality = q
                            best_quality_score = score
                except Exception as e:
                    logger.warning(f"品质模板匹配异常: {template_name}, {e}")
                    continue

            if not best_quality:
                return None

            # ── 属性 TemplateMatch（全部识别，取最高分） ──────────
            best_attr = None
            best_attr_score = 0.0
            for a in self.ATTRIBUTES:
                template_name = f"藏宝图{a}.png"
                try:
                    reco_detail = context.run_recognition_direct(
                        JRecognitionType.TemplateMatch,
                        JTemplateMatch(
                            template=[template_name],
                            roi=self.ATTRIBUTE_ROI,
                            threshold=[self.THRESHOLD],
                        ),
                        img,
                    )
                    if reco_detail and reco_detail.hit and reco_detail.best_result:
                        score = reco_detail.best_result.score
                        if score > best_attr_score:
                            best_attr = a
                            best_attr_score = score
                except Exception as e:
                    logger.warning(f"属性模板匹配异常: {template_name}, {e}")
                    continue

            if not best_attr:
                return None

            # ── 校验组合是否在 attach 中 ───────────────────────
            combined = f"{best_quality}{best_attr}"
            logger.info(
                f"已进入藏宝图:  {combined}"
                f"（品质={best_quality} ,"
                f" 属性={best_attr}）"
            )
            if combined in attach:
                logger.info(f"藏宝图: {combined} 在选择的组合中")
                return CustomRecognition.AnalyzeResult(
                    box=[0, 0, 0, 0],
                    detail={
                        "quality": best_quality,
                        "attribute": best_attr,
                        "combined": combined,
                    },
                )
            else:
                logger.info(f"藏宝图: {combined} 不在选择的组合中")
                return None

        except Exception as e:
            logger.error(f"TreasureMapQualityAttributeCheck 执行出错: {e}")
            return None
