"""Consume native recognition and compile native click pipelines; never capture or send input."""
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from custom.pipeline_params import parse_pipeline_json_param
from utils.intelligence_cards import P,iter_ocr_boxes,empty_cells,apply_hand_plan,hand_is_visible
from utils.intelligence_live import IntelligenceSession,observation,click_plans
from utils.runtime_paths import get_runtime_paths
from utils.logger import logger

_SESSIONS={}

def session():
    path=get_runtime_paths().data_dir/'intelligence-battle-state.json'
    key=str(path)
    if key not in _SESSIONS:_SESSIONS[key]=IntelligenceSession(path)
    return _SESSIONS[key]


@AgentServer.custom_action('WarmIntelligenceStrategy')
class WarmIntelligenceStrategy(CustomAction):
    def run(self,context,argv):
        state=session();state.reset()
        if not state.warm():logger.warning(f'情报模拟战策略回退: {state.reason}')
        return True


@AgentServer.custom_action('PlanIntelligenceHand')
class PlanIntelligenceHand(CustomAction):
    def run(self,context,argv):
        param=parse_pipeline_json_param(argv.custom_action_param)
        items=iter_ocr_boxes(argv.reco_detail)
        if not hand_is_visible(items):return context.override_next(argv.node_name,[argv.node_name])
        seen=observation(items,empty_cells(argv.reco_detail))
        if seen['health']==0:return context.override_next(argv.node_name,[P+'等待对局'])
        state=session();round_number=param['round']
        plan=state.prepare(seen,round_number,param['refreshes'])
        after=P+('刷新手牌' if plan['next_action']=='refresh' else '准备就绪')
        placements=[f"{a['card']}→第{a['cell']//3+1}行第{a['cell']%3+1}列" for a in plan['actions']]
        logger.info(f"情报模拟战策略: round={round_number} gold={seen['gold']} health={seen['health']} mode={plan['mode']} placements={placements} next={plan['next_action']}")
        if plan['mode']!='scored':logger.warning(f'情报模拟战降级: {state.reason}')
        if plan['actions']:
            if not context.override_pipeline({P+'确认落位':{'action':{'param':{
                'custom_action_param':{'round':round_number,'after':after}}}}}):return False
            return apply_hand_plan(context,argv.node_name,click_plans(plan['actions']),P+'确认落位')
        return context.override_next(argv.node_name,[after])


@AgentServer.custom_action('ConfirmIntelligenceHand')
class ConfirmIntelligenceHand(CustomAction):
    def run(self,context,argv):
        param=parse_pipeline_json_param(argv.custom_action_param)
        seen=observation(iter_ocr_boxes(argv.reco_detail),empty_cells(argv.reco_detail))
        state=session()
        if not state.confirm(seen,param['round']):logger.warning(f'情报模拟战落位未确认，暂用保守选牌: {state.reason}')
        return context.override_next(argv.node_name,[param['after']])


@AgentServer.custom_action('ResetIntelligenceRounds')
class ResetIntelligenceRounds(CustomAction):
    def run(self,context,argv):
        for i in range(1,6):context.clear_hit_count(P+f'第{i}回合')
        return True
