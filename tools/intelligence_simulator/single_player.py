"""五回合单边回归：真实张数、五槽商店、主动刷新不补空槽，累计100提前结束。"""
from __future__ import annotations

from collections import Counter
import math
import random
import re
import statistics
import time

from .model import BY_NAME, CARDS, simulate
from .refresh import analyze_hand, lookup_coin_value

WHITELIST=re.compile(r'(小黑|苍牙|仓牙|琳|阿力|小椒|赤芒|焚天|黑龙|[风凤]林火山战旗|\S*覆面)$')


def _whitelist(raw, hand, refreshes):
    gold=raw['gold'];empty=[i for i,c in enumerate(raw['board']) if c is None];actions=[]
    for slot,name in enumerate(hand):
        if empty and WHITELIST.search(name) and BY_NAME[name]['cost']<=gold:
            actions.append({'shop_slot':slot,'card':name,'cell':empty.pop(0)})
            gold-=BY_NAME[name]['cost']
    return {'actions':actions,'next_action':'refresh' if refreshes and len(hand)>len(actions) else 'prepare'}


def play(seed, strategy, reference):
    if strategy not in {'whitelist','damage_only','v1'}:raise ValueError(strategy)
    rng=random.Random(seed)
    deck=[c['name'] for c in CARDS for _ in range(c['copies'])]
    total_cards=Counter(deck)
    board=[None]*9;shop=[None]*5;gold=5;previous_bought=0;total_damage=0
    round_trace=[];decision_times=[];partial_refreshes=0;zero_buy_refreshes=0
    def draw():
        return deck.pop(rng.randrange(len(deck))) if deck else None
    def inventory_check():
        current=Counter(deck)+Counter(c for c in shop if c)+Counter(c['name'] for c in board if c)
        assert current==total_cards,'单边牌库张数失衡'
    started=time.perf_counter()
    for turn in range(1,6):
        if turn>1:gold+=3+(2 if previous_bought==0 else 1 if previous_bought==1 else 0)
        deck.extend(c for c in shop if c)
        shop=[draw() for _ in range(5)]  # 自动刷新会补齐原有空槽。
        refreshes=1;bought=0;events=[]
        while True:
            inventory_check()
            slots=[i for i,c in enumerate(shop) if c]
            hand=[shop[i] for i in slots]
            raw={'round':turn,'gold':gold,'board':board}
            value=lookup_coin_value(reference,turn,board.count(None)) if strategy=='v1' else 0
            begin=time.perf_counter()
            plan=_whitelist(raw,hand,refreshes) if strategy=='whitelist' else analyze_hand(raw,hand,value,refreshes)
            decision_times.append((time.perf_counter()-begin)*1000)
            before_gold=gold
            for action in plan['actions']:
                slot=slots[action['shop_slot']];name=action['card'];cell=action['cell']
                assert shop[slot]==name and board[cell] is None
                cost=BY_NAME[name]['cost'];assert gold>=cost
                gold-=cost;board[cell]={'name':name,'entered_round':turn};shop[slot]=None;bought+=1
            events.append({'hand':hand,'bought':[a['card'] for a in plan['actions']],
                           'gold_before':before_gold,'gold_left':gold,'coin_value':value,
                           'next_action':plan['next_action']})
            inventory_check()
            if plan['next_action']!='refresh':break
            assert refreshes>0
            if plan['actions'] and gold>0:partial_refreshes+=1
            if not plan['actions']:zero_buy_refreshes+=1
            refreshes-=1
            # 仅替换未购买的槽。先全部归还，再无放回抽取，允许抽回旧牌。
            positions=[i for i,c in enumerate(shop) if c]
            deck.extend(shop[i] for i in positions)
            for i in positions:shop[i]=None
            for i in positions:shop[i]=draw()
        raw={'round':turn,'gold':gold,'board':board,'pool_override':{}}
        evaluated=simulate(raw,profile='refresh_v1',seconds=2)
        damage=evaluated['best_round_damage'][turn-1]
        total_damage+=damage
        # 只把本回合实际产币加到账户；下一回合3金币和少买奖励在下一轮开始发。
        elements={BY_NAME[c['name']]['element'] for c in board if c and BY_NAME[c['name']]['element']}
        income=sum(1 if BY_NAME[c['name']]['effect']=='income' else len(elements)
                   if BY_NAME[c['name']]['effect']=='amulet' else 0 for c in board if c)
        gold+=income;previous_bought=bought
        round_trace.append({'round':turn,'damage':damage,'cumulative_damage':total_damage,
                            'bought':bought,'income':income,'gold_at_end':gold,'events':events})
        inventory_check()
        if total_damage>=100:break
    return {'seed':seed,'strategy':strategy,'reached_100':total_damage>=100,
            'hit_round':len(round_trace) if total_damage>=100 else None,
            'total_damage':total_damage,'rounds_played':len(round_trace),
            'round_damage':[r['damage'] for r in round_trace],
            'partial_purchase_refreshes':partial_refreshes,'zero_purchase_refreshes':zero_buy_refreshes,
            'decision_ms':decision_times,'elapsed_s':time.perf_counter()-started,'trace':round_trace}


def aggregate(games):
    timings=sorted(ms for g in games for ms in g['decision_ms'])
    hits=[g['hit_round'] for g in games if g['reached_100']]
    damages=[g['total_damage'] for g in games]
    return {'games':len(games),'reach_100_rate':len(hits)/len(games),
            'hit_round_counts':{str(r):hits.count(r) for r in range(1,6)},
            'mean_hit_round_among_successes':statistics.mean(hits) if hits else None,
            'mean_damage':statistics.mean(damages),'median_damage':statistics.median(damages),
            'min_damage':min(damages),'max_damage':max(damages),
            'decision_median_ms':statistics.median(timings),
            'decision_p95_ms':timings[math.ceil(len(timings)*.95)-1],
            'decision_max_ms':max(timings),
            'partial_purchase_refreshes':sum(g['partial_purchase_refreshes'] for g in games),
            'zero_purchase_refreshes':sum(g['zero_purchase_refreshes'] for g in games)}


def run_regression(count,first_seed,reference):
    if not 1<=count<=10000:raise ValueError('games必须为1..10000')
    started=time.perf_counter();report={}
    for strategy in ['whitelist','damage_only','v1']:
        games=[play(seed,strategy,reference) for seed in range(first_seed,first_seed+count)]
        report[strategy]={'summary':aggregate(games),'games':games}
    return {'version':'refresh-v1-first-pass','first_seed':first_seed,'games_per_strategy':count,
            'elapsed_s':time.perf_counter()-started,'profile':'refresh_v1',
            'evaluation':'累计到100即停止，越早越好；未达100时比较第五回合累计伤害。策略本身仍用到第五回合累计增伤＋金币项，不加提前结束偏好。',
            'reference':reference,'strategies':report,
            'limitations':['单边牌库，不扣对手牌；无锁牌/撤回/未知潜力分。',
                           '游戏规则未实测部分沿用模型假设，结果不是实机胜率。',
                           '白名单为原名单/顺序买入/首空格的离线对照，全部策略使用相同白板规则。',
                           '每个策略用相同种子区间；后续发牌随购买/刷新分岔，不能视作逐手完全相同。',
                           '金币系数先由单张余池参考确定，未按本次测试结果二次调参。']}
