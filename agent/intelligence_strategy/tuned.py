"""本手所有可买组合与落位统一估值；不模拟未来发牌。"""
from copy import deepcopy
import math
import time

from .model import BY_NAME,CARDS,prepare_state
from .refresh import hand_choices,purchase_actions

DEFAULT_POLICY = {
    'gold_before_refresh':[12,9.6,7.2,4.8,2.4],
    'gold_after_refresh':[8,6,4,2,0],
    'heuristics':{'aura_weight':1,'role_position_bias':1},
    'prioritize_finish':True,
    'refresh_slot_budget':3,
}


def resolve_policy(overrides=None):
    if overrides is not None and not isinstance(overrides,dict):
        raise ValueError('策略必须是JSON对象')
    overrides=overrides or {}
    if set(overrides)-DEFAULT_POLICY.keys():
        raise ValueError('未知策略参数')
    policy=deepcopy(DEFAULT_POLICY)
    policy.update(deepcopy(overrides))
    policy['heuristics']=dict(DEFAULT_POLICY['heuristics'],**overrides.get('heuristics',{}))
    if not isinstance(policy.get('prioritize_finish',True),bool):
        raise ValueError('prioritize_finish必须为布尔值')
    for phase in ('gold_before_refresh','gold_after_refresh'):
        values=policy[phase]
        if len(values)!=5 or any(not math.isfinite(v) or v<0 for v in values):
            raise ValueError('金币权重必须为5个非负有限数')
    if policy['gold_after_refresh'][-1]!=0:
        raise ValueError('第五回合刷新后金币价值必须为0')
    if any(a<b for a,b in zip(policy['gold_before_refresh'],policy['gold_after_refresh'])):
        raise ValueError('刷新前金币价值不能低于刷新后')
    if not math.isfinite(policy['refresh_slot_budget']) or policy['refresh_slot_budget']<0:
        raise ValueError('刷新槽位预算必须有限且非负')
    return policy


def analyze_tuned(raw,hand,refreshes=1, *, policy=None, cumulative_damage=0):
    if not isinstance(refreshes,int) or refreshes<0:
        raise ValueError('refreshes必须是非负整数')
    if not isinstance(hand,list):
        raise ValueError('hand必须是最多5张有效牌名')
    started=time.perf_counter();policy=resolve_policy(policy)
    remaining=prepare_state(raw)['pool']
    heuristics=dict(policy.get('heuristics',{}),cumulative_damage=cumulative_damage,finish_priority=int(policy.get('prioritize_finish',True)))
    turn=raw.get('round',1)
    shop_slots=raw.get('shop_slots',len(hand))
    if not isinstance(shop_slots,int) or not len(hand)<=shop_slots<=5:
        raise ValueError('shop_slots必须包含全部已识别手牌且不超过5')
    result=hand_choices(dict(raw,refreshes=refreshes,shop_slots=shop_slots),hand,synergy=True,heuristics=heuristics)
    for c in result['choices']:
        pool=remaining.copy()
        for name in c['cards']:pool[BY_NAME[name]['id']]-=1
        minimum=min((card['cost'] for card,n in zip(CARDS,pool) if n),default=math.inf)
        c['will_refresh']=bool(refreshes and len(c['cards'])<shop_slots and c['empty_left'] and c['gold_left']>=minimum)
        c['refresh_slots']=shop_slots-len(c['cards']) if c['will_refresh'] else 0
        c['gold_phase']='before_refresh' if c['will_refresh'] else 'after_refresh'
        c['coin_value']=policy['gold_'+c['gold_phase']][turn-1]
        c['cash_for_refresh']=min(c['valued_gold'],policy.get('refresh_slot_budget',3)*(shop_slots-len(c['cards']))) if c['will_refresh'] else 0
        c['cash_for_later']=c['valued_gold']-c['cash_for_refresh']
        c['gold_value']=(c['cash_for_refresh']*policy['gold_before_refresh'][turn-1]
                         +c['cash_for_later']*policy['gold_after_refresh'][turn-1])
        # Future coin production is deliberately worth zero in operation scoring.
        c['income_potential']=0
        c['score']=c['adjusted_damage']+(c['gold_value'] if not c['finishing'] else 0)
    chosen=max(result['choices'],key=lambda c:(c['finishing'],c['score'],c['damage'],c['gold_left'],c['position_priority']))
    return {'chosen':chosen,'actions':purchase_actions(raw,hand,chosen),'score':chosen['score'],
            'coin_value':chosen['coin_value'],'gold_phase':chosen['gold_phase'],
            'next_action':'refresh' if chosen['will_refresh'] else 'prepare',
            'elapsed_s':time.perf_counter()-started,'engine_s':result['elapsed_s'],'policy':policy,
            'candidates_evaluated':len(result['choices']),
            'score_unit':'immediate_damage' if chosen['finishing'] else 'estimated_damage'}
