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
from .tuned import analyze_tuned,resolve_policy

WHITELIST=re.compile(r'(小黑|苍牙|仓牙|琳|阿力|小椒|赤芒|焚天|黑龙|[风凤]林火山战旗|\S*覆面)$')


def _whitelist(raw, hand, refreshes):
    gold=raw['gold'];empty=[i for i,c in enumerate(raw['board']) if c is None];actions=[]
    for slot,name in enumerate(hand):
        if empty and WHITELIST.search(name) and BY_NAME[name]['cost']<=gold:
            actions.append({'shop_slot':slot,'card':name,'cell':empty.pop(0)})
            gold-=BY_NAME[name]['cost']
    return {'actions':actions,'next_action':'refresh' if refreshes and len(hand)>len(actions) else 'prepare'}


def play(seed, strategy, reference=None, *, policy=None, stop_at_100=True):
    if strategy not in {'whitelist','damage_only','v1','fixed7','synergy_v2','tuned'}:raise ValueError(strategy)
    rng=random.Random(seed)
    deck=[c['name'] for c in CARDS for _ in range(c['copies'])]
    total_cards=Counter(deck)
    board=[None]*9;shop=[None]*5;gold=5;previous_bought=0;total_damage=0
    hit_round=None;damage_at_first_100=None
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
            value=lookup_coin_value(reference,turn,board.count(None)) if strategy=='v1' else 7 if strategy in {'fixed7','synergy_v2','tuned'} else 0
            begin=time.perf_counter()
            if strategy=='tuned':
                plan=analyze_tuned(raw,hand,refreshes,policy=policy,cumulative_damage=total_damage)
                value=plan['coin_value']
            else:
                plan=_whitelist(raw,hand,refreshes) if strategy=='whitelist' else analyze_hand(raw,hand,value,refreshes,synergy=strategy=='synergy_v2',explain=False)
            decision_times.append((time.perf_counter()-begin)*1000)
            before_gold=gold
            for action in plan['actions']:
                slot=slots[action['shop_slot']];name=action['card'];cell=action['cell']
                assert shop[slot]==name and board[cell] is None
                cost=BY_NAME[name]['cost'];assert gold>=cost
                gold-=cost;board[cell]={'name':name,'entered_round':turn};shop[slot]=None;bought+=1
            events.append({'hand':hand,'bought':[a['card'] for a in plan['actions']],
                           'gold_before':before_gold,'gold_left':gold,'coin_value':value,
                           'next_action':plan['next_action'],'refresh_available':refreshes,
                           'board_after':[c['name'] if c else None for c in board],
                           'forecast':{k:v for k,v in plan['forecast'].items() if k not in {'elapsed_s','build_s'}} if plan.get('forecast') else None})
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
        if total_damage>=100 and hit_round is None:
            hit_round=turn;damage_at_first_100=total_damage
        if hit_round is not None and stop_at_100:break
    return {'seed':seed,'strategy':strategy,'reached_100':total_damage>=100,
            'hit_round':hit_round,'damage_at_first_100':damage_at_first_100,
            'actual_stop_damage':damage_at_first_100 if hit_round else total_damage,
            'five_round_damage':total_damage if len(round_trace)==5 else None,
            'total_damage':total_damage,'rounds_played':len(round_trace),
            'round_damage':[r['damage'] for r in round_trace],
            'partial_purchase_refreshes':partial_refreshes,'zero_purchase_refreshes':zero_buy_refreshes,
            'decision_ms':decision_times,'elapsed_s':time.perf_counter()-started,'trace':round_trace}


def aggregate(games):
    timings=sorted(ms for g in games for ms in g['decision_ms'])
    hits=[g['hit_round'] for g in games if g['reached_100']]
    damages=[g.get('actual_stop_damage',g['total_damage']) for g in games]
    full=[g['five_round_damage'] for g in games if g.get('five_round_damage') is not None]
    return {'games':len(games),'four_round_kill_rate':sum(r<=4 for r in hits)/len(games),
            'mean_five_round_damage':statistics.mean(full) if len(full)==len(games) else None,
            'reach_100_rate':len(hits)/len(games),
            'hit_round_counts':{str(r):hits.count(r) for r in range(1,6)},
            'mean_hit_round_among_successes':statistics.mean(hits) if hits else None,
            'mean_damage':statistics.mean(damages),'median_damage':statistics.median(damages),
            'min_damage':min(damages),'max_damage':max(damages),
            'decision_median_ms':statistics.median(timings),
            'decision_p95_ms':timings[math.ceil(len(timings)*.95)-1],
            'decision_max_ms':max(timings),
            'partial_purchase_refreshes':sum(g['partial_purchase_refreshes'] for g in games),
            'zero_purchase_refreshes':sum(g['zero_purchase_refreshes'] for g in games)}


def run_regression(count,first_seed,reference=None,strategies=None, *, policy=None, full_five_rounds=False):
    if not 1<=count<=10000:raise ValueError('games必须为1..10000')
    started=time.perf_counter();report={}
    for strategy in (strategies or ['damage_only','synergy_v2','tuned']):
        games=[play(seed,strategy,reference,policy=policy,stop_at_100=not full_five_rounds) for seed in range(first_seed,first_seed+count)]
        summary=aggregate(games)
        report[strategy]={'summary':summary,'acceptance_actual_stop':target_checks(summary),
                          'acceptance_five_rounds':target_checks(summary,five_rounds=True),'games':games}
    return {'version':'refresh-stage-v3','first_seed':first_seed,'games_per_strategy':count,
            'elapsed_s':time.perf_counter()-started,'profile':'refresh_v1',
            'evaluation':'首次累计100记录击杀回合；mean_damage始终为提前结束实际伤害，full_five_rounds额外提供固定五回合总伤害；不混用两种均值。',
            'reference':reference,'policy':resolve_policy(policy),
            'full_five_rounds':full_five_rounds,'strategies':report,
            'limitations':['单边牌库，不扣对手牌；无锁牌/撤回；synergy_v2/tuned含启发式被动潜力；tuned含空格buff/经济潜力与占位成本。',
                           '游戏规则未实测部分沿用模型假设，结果不是实机胜率。',
                           '白名单为原名单/顺序买入/首空格的离线对照，全部策略使用相同白板规则。',
                           '每个策略用相同种子区间；后续发牌随购买/刷新分岔，不能视作逐手完全相同。',
                           'fixed7和synergy_v2金币系数固定7；tuned区分刷新阶段并经过离线调参；v1沿用旧表。']}


def target_checks(summary, *, five_rounds=False):
    mean=summary['mean_five_round_damage'] if five_rounds else summary['mean_damage']
    checks={'mean_130':None if mean is None else mean>=130,
            'five_round_100_rate_99pct':summary['reach_100_rate']>=.99,
            'four_round_kill_rate_20pct':summary['four_round_kill_rate']>=.2}
    return dict(checks,all_met=all(v is True for v in checks.values()))
