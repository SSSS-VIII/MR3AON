"""第一版离线刷新策略：可见手牌子集＋金币机会成本；无设备接口。"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from copy import deepcopy
from fractions import Fraction
import math
import time

from .model import BY_NAME, CARDS, prepare_state, simulate

PROFILE = 'refresh_v1'


def _quantile(rows, fraction):
    total = sum(weight for _, weight in rows)
    if not total:
        return 0.0
    ordered=sorted(rows)
    def value_at(rank):
        accumulated=0
        for value,weight in ordered:
            accumulated+=weight
            if accumulated>=rank:return value
        raise AssertionError(rank)
    if fraction==.5:
        return float((value_at((total+1)//2)+value_at((total+2)//2))/2)
    return float(value_at(max(1,math.ceil(total*fraction))))


def coin_reference(raw):
    """临时参考：全余池单张补牌的最优增伤/费用，按剩余张数加权。不是刷新期望。"""
    started = time.perf_counter()
    state = prepare_state(raw)
    result = simulate(raw, profile=PROFILE, max_purchases=1, trace_choices=True,
                      position_tiebreak=True, seconds=2)
    if not result['complete']:
        raise RuntimeError('单张金币参考计算未完成，不发布部分结果')
    ratios = []
    for choice in result['choices']:
        if not choice['cards']:
            continue
        card = BY_NAME[choice['cards'][0]]
        ratios.append((Fraction(choice['damage_gain'], card['cost']), state['pool'][card['id']]))
    count = sum(weight for _, weight in ratios)
    return {'round':state['round'], 'empty':state['empty'], 'reference_gold':state['gold'],
            'pool_cards':sum(state['pool']), 'eligible_copies':count,
            'mean':float(sum(value*weight for value,weight in ratios)/count) if count else 0,
            'p25':_quantile(ratios,.25), 'median':_quantile(ratios,.5), 'p75':_quantile(ratios,.75),
            'elapsed_s':time.perf_counter()-started, 'engine_s':result['elapsed_s'],
            'profile':PROFILE, 'unit':'当前至第五回合的增伤/金币',
            'method':'单张最优落位单位增伤的剩余份数加权分布；非5槽刷新期望；未含后续购买协同/空位潜力。'}


def after_purchase(raw, choice):
    state = deepcopy(raw)
    original = raw.get('board',[None]*9)
    state['board'] = [deepcopy(old) if old is not None else
                      {'name':name,'entered_round':raw.get('round',1)} if name else None
                      for old,name in zip(original,choice['board'])]
    state['gold'] = choice['gold_left']
    if 'pool_override' in state:
        left=Counter(state['pool_override']);left.subtract(choice['cards'])
        state['pool_override']={name:count for name,count in left.items() if count>0}
    return state


def spendable_gold(raw, choice):
    """已满的棋盘不能再靠剩余金币获得新牌；亦不把超过剩余卡位容量的钱全估值。"""
    state=prepare_state(after_purchase(raw,choice))
    costs=sorted((card['cost'] for card,n in zip(CARDS,state['pool']) for _ in range(n)),reverse=True)
    return min(choice['gold_left'],sum(costs[:state['empty']]))


def hand_choices(raw, hand):
    if not isinstance(hand,list) or len(hand)>5 or any(name not in BY_NAME for name in hand):
        raise ValueError('hand必须是最多5张有效牌名')
    full=prepare_state(raw)
    requested=Counter(hand)
    for name,n in requested.items():
        if n>full['pool'][BY_NAME[name]['id']]:
            raise ValueError(f'{name}手牌张数超过单边已知余量')
    partial=deepcopy(raw);partial['pool_override']=dict(requested)
    result=simulate(partial,profile=PROFILE,trace_choices=True,position_tiebreak=True,seconds=2)
    if not result['complete']:
        raise RuntimeError('当前手牌搜索未完成，不作为已完成决策')
    for choice in result['choices']:
        choice['valued_gold']=spendable_gold(raw,choice)
        choice['empty_left']=choice['board'].count(None)
    return result


def sensitivity_frontier(choices):
    """给出λ≥0时，D+λ×可用剩余金币的精确交点；不把预设权重伪装成定论。"""
    frontier=[]
    for i,choice in enumerate(choices):
        low=Fraction(0);high=None
        for j,other in enumerate(choices):
            if i==j:continue
            d=choice['damage']-other['damage'];g=choice['valued_gold']-other['valued_gold']
            if g==0:
                if d<0:high=Fraction(-1);break
            elif g>0:low=max(low,Fraction(-d,g))
            else:
                boundary=Fraction(d,-g)
                high=boundary if high is None else min(high,boundary)
        if high is None or low<=high:
            frontier.append({'cards':choice['cards'],'damage':choice['damage'],
                             'gold_left':choice['gold_left'],'valued_gold':choice['valued_gold'],
                             'lambda_from':float(low),'lambda_to':float(high) if high is not None else None})
    return frontier


def select_choice(choices, coin_value):
    if not math.isfinite(coin_value) or coin_value<0:
        raise ValueError('金币价值必须为有限非负数')
    def key(choice):
        return (choice['damage']+coin_value*choice['valued_gold'],choice['gold_left'],
                choice['empty_left'],choice['position_priority'])
    return max(choices,key=key)


def purchase_actions(raw,hand,choice):
    available=defaultdict(deque)
    for index,name in enumerate(hand):available[name].append(index)
    actions=[]
    for cell,(old,name) in enumerate(zip(raw.get('board',[None]*9),choice['board'])):
        if old is None and name is not None:
            actions.append({'card':name,'shop_slot':available[name].popleft(),'cell':cell})
    return actions


def analyze_hand(raw,hand,coin_value,refreshes=1):
    started=time.perf_counter()
    result=hand_choices(raw,hand)
    chosen=select_choice(result['choices'],coin_value)
    after=after_purchase(raw,chosen)
    pool=prepare_state(after)['pool']
    min_cost=min((card['cost'] for card,n in zip(CARDS,pool) if n),default=math.inf)
    replaceable=len(hand)-len(chosen['cards'])  # 已买空的槽位不会被主动刷新补齐。
    can_refresh=(refreshes>0 and replaceable>0 and chosen['empty_left']>0 and chosen['gold_left']>=min_cost)
    return {'chosen':chosen,'actions':purchase_actions(raw,hand,chosen),
            'coin_value':coin_value,'score':chosen['damage']+coin_value*chosen['valued_gold'],
            'next_action':'refresh' if can_refresh else 'prepare','replaceable_shop_slots':replaceable,
            'frontier':sensitivity_frontier(result['choices']), 'choices':result['choices'],
            'elapsed_s':time.perf_counter()-started,'engine_s':result['elapsed_s'],
            'latent_empty_cell_value':0,'inactive_synergy_value':0,
            'future_coin_income_note':'end_gold仅展示；本版尚未把经济卡未来产币另折算进当前金币项。'}


def reference_scenarios():
    boards=[[],['神乐·琳','鬼狩·苍牙','雷兽·阿力'],
            ['神乐·琳','鬼狩·苍牙','雷兽·阿力','超威·阿力','修罗覆面'],
            ['神乐·琳','鬼狩·苍牙','雷兽·阿力','超威·阿力','修罗覆面','赤芒','VVIP黑卡']]
    return [{'name':f'r{turn}-e{9-len(board)}','round':turn,'gold':6,'board':board+[None]*(9-len(board))}
            for turn in range(1,6) for board in boards if turn>=3 or len(board)<=3 and turn>=2 or not board]


def build_reference_table():
    return {'profile':PROFILE,'method':'单张单位增伤中位数作为临时金币参考，非最终标定',
            'rows':[coin_reference(state)|{'name':state['name']} for state in reference_scenarios()]}


def lookup_coin_value(table,turn,empty):
    if table.get('complete_reference') is False or (table.get('method')=='whole_pool_gain_per_actual_spent_coin' and not table.get('complete_reference')):
        raise ValueError('全池金币参考尚未算完，不能静默使用截断表')
    if table.get('profile',PROFILE)!=PROFILE:
        raise ValueError('金币参考与策略白板规则不一致')
    rows=[row for row in table['rows'] if row['round']==turn]
    if not rows or not empty:return 0
    row=min(rows,key=lambda row:abs(row['empty']-empty))
    return row['gold_value'] if 'gold_value' in row else row['median']
