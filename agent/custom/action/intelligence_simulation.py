"""仅解析原生识别结果并编排原生点击；不截图、不识图、不发送设备输入。"""
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from custom.pipeline_params import parse_pipeline_json_param
from utils.intelligence_cards import P, plan_cards, iter_ocr_boxes, empty_cells, apply_hand_plan, hand_is_visible
from utils.logger import logger

@AgentServer.custom_action('PlanIntelligenceHand')
class PlanIntelligenceHand(CustomAction):
    def run(self, context, argv):
        after=parse_pipeline_json_param(argv.custom_action_param)['after']
        items = iter_ocr_boxes(argv.reco_detail)
        if not hand_is_visible(items):
            return context.override_next(argv.node_name, [argv.node_name])
        plans = plan_cards(items, empty_cells(argv.reco_detail))
        logger.info(f'情报模拟战批量手牌: count={len(plans)}, roles={[p[2] for p in plans]}')
        return apply_hand_plan(context, argv.node_name, plans, after)


@AgentServer.custom_action('ResetIntelligenceRounds')
class ResetIntelligenceRounds(CustomAction):
    def run(self,context,argv):
        for i in range(1,6):context.clear_hit_count(P+f'第{i}回合')
        return True
