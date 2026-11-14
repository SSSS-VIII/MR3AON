"""按刷新阶段分开估值金币，联合搜索本手子集/落位；纯离线。"""
from copy import deepcopy
import math
import time

from .model import BY_NAME,CARDS,prepare_state
from .refresh import hand_choices,purchase_actions
from .forecast import forecast_choices

DEFAULT_POLICY = {
    'gold_before_refresh':[6,4.8,3.6,2.4,1.2],
    'gold_after_refresh':[4,3,2,1,0],
    'heuristics':{'aura_weight':2,'vacancy_weight':3,'role_position_bias':1},
    'income_weight':2,
    'prioritize_finish':True,
    'refresh_slot_budget':3,
    'lookahead_weight':1,
    'lookahead_gold_scale':1,
    'lookahead_seconds':.65,
    'lookahead_mode':'rollout',
    'position_candidates':1,
    'rollout_samples':64,
    'rollout_width':8,
    'rollout_candidates':6,
    'rollout_safety_penalty':50,
    'rollout_early_bonus':10,
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
    for key in ('income_weight','refresh_slot_budget','lookahead_weight','lookahead_gold_scale','lookahead_seconds','rollout_safety_penalty','rollout_early_bonus'):
        if not math.isfinite(policy.get(key,0)) or policy.get(key,0)<0:
            raise ValueError('策略权重必须有限且非负')
    if not 0<=policy['lookahead_weight']<=1 or not 0<policy['lookahead_seconds']<=1:
        raise ValueError('lookahead_weight须在0..1，lookahead_seconds须在0..1内')
    if policy['lookahead_mode'] not in {'single','rollout'}:
        raise ValueError('未知前瞻方式')
    for key,maximum in [('position_candidates',8),('rollout_samples',64),('rollout_width',16),('rollout_candidates',32)]:
        if not isinstance(policy[key],int) or not 1<=policy[key]<=maximum:
            raise ValueError('rollout规模超出范围')
    return policy


def analyze_tuned(raw,hand,refreshes=1, *, policy=None, cumulative_damage=0):
    if not isinstance(refreshes,int) or refreshes<0:
        raise ValueError('refreshes必须是非负整数')
    started=time.perf_counter();policy=resolve_policy(policy)
    remaining=prepare_state(raw)['pool']
    heuristics=dict(policy.get('heuristics',{}),cumulative_damage=cumulative_damage,finish_priority=int(policy.get('prioritize_finish',True)))
    result=hand_choices(raw,hand,synergy=True,heuristics=heuristics,position_candidates=policy['position_candidates'] if policy['lookahead_weight'] else 1)
    turn=raw.get('round',1)
    shop_slots=raw.get('shop_slots',len(hand))
    if not isinstance(shop_slots,int) or not len(hand)<=shop_slots<=5:
        raise ValueError('shop_slots必须包含全部已识别手牌且不超过5')
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
        # Future income must fit in the remaining spend capacity. No value for
        # coins received after round 5, and no income with a full board.
        elements={BY_NAME[n]['element'] for n in c['board'] if n and BY_NAME[n]['element']}
        producers=[BY_NAME[n]['effect'] for n in c['board'] if n and BY_NAME[n]['effect'] in {'income','amulet'}]
        capacity=max(0,2.5*c['empty_left']-c['gold_left']-3*(5-turn))
        c['income_potential']=0
        for r in range(turn,5):
            income=sum(1 if effect=='income' else min(4,len(elements)+.5*(r-turn)) for effect in producers)
            useful=min(capacity,income);capacity-=useful
            c['income_potential']+=useful*policy['gold_before_refresh'][r]
        c['income_potential']*=policy.get('income_weight',0)
        c['score']=c['adjusted_damage']+(c['gold_value']+c['income_potential'] if not c['finishing'] else 0)
    forecast=forecast_choices(raw,result['choices'],policy,cumulative_damage=cumulative_damage) if policy['lookahead_weight'] else None
    chosen=max((c for c in result['choices'] if c.get('decision_eligible',True)),key=lambda c:(c['finishing'],c['score'],c['damage'],c['gold_left'],c['position_priority']))
    return {'chosen':chosen,'actions':purchase_actions(raw,hand,chosen),'score':chosen['score'],
            'coin_value':chosen['coin_value'],'gold_phase':chosen['gold_phase'],
            'next_action':'refresh' if chosen['will_refresh'] else 'prepare',
            'elapsed_s':time.perf_counter()-started,'engine_s':result['elapsed_s'],'policy':policy,'forecast':forecast}
