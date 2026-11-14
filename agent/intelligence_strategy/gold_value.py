"""从完整全池组合数据估金币价；不以预算代替实际消费，不以单张统计代替组合收益。"""
from __future__ import annotations

from fractions import Fraction
import json
import math
from pathlib import Path

from .model import CARDS, prepare_state, simulate


def spending_distribution(raw):
    state=prepare_state(raw);gold=state['gold'];empty=state['empty']
    dp={(0,0):(1,1)}
    for card,left in zip(CARDS,state['pool']):
        out={}
        for (spent,used),(unique,physical) in dp.items():
            for k in range(min(left,(gold-spent)//card['cost'],empty-used)+1):
                key=spent+k*card['cost'],used+k
                a,b=out.get(key,(0,0))
                out[key]=(a+unique,b+physical*math.comb(left,k))
        dp=out
    grouped={}
    for (spent,_),(unique,physical) in dp.items():
        a,b=grouped.get(spent,(0,0));grouped[spent]=(a+unique,b+physical)
    return [{'spent':spent,'unique_combinations':a,'physical_subsets':b}
            for spent,(a,b) in sorted(grouped.items())]


def estimate_gold_value(raw,result):
    if result['mode']!='exact' or not result['complete']:
        raise ValueError('金币参考必须来自已完成的全池精确统计，不能用采样或截断前缀')
    if result.get('max_purchases') is not None:
        raise ValueError('不能把单张/限张数统计冒充全组合估值')
    grouped=spending_distribution(raw)
    total=sum(row['physical_subsets'] for row in grouped)
    assert total==result['physical_subsets']
    assert sum(row['unique_combinations'] for row in grouped)==result['combinations']
    spent_sum=sum(row['spent']*row['physical_subsets'] for row in grouped)
    gain_sum=sum(gain*physical for gain,unique,physical in result['histogram'])
    ratio=Fraction(gain_sum,spent_sum) if spent_sum else Fraction(0)
    gain_median=result['statistics']['physical_subsets']['damage_gain']['median']
    state=prepare_state(raw)
    return {'name':raw.get('name','custom'),'round':state['round'],'empty':state['empty'],
            'budget':state['gold'],'profile':result.get('profile','full'),
            'gold_value':max(0,float(ratio)), 'unclamped_gold_value':float(ratio),
            'mean_gain':gain_sum/total,'median_gain':gain_median,'mean_actual_spent':spent_sum/total,
            'weighted_gain_sum':gain_sum,'weighted_spent_sum':spent_sum,'physical_subsets':total,
            'combinations':result['combinations'],'engine_s':result['elapsed_s'],
            'ratio_numerator':ratio.numerator,'ratio_denominator':ratio.denominator,
            'spending_distribution':grouped,
            'method':'整池组合份数加权总增伤 / 同口径总实际花费；平均金币效率，不是精确刷新边际期望。'}


def load_historical(path):
    data=json.loads(Path(path).read_text());states={s['name']:s for s in data['scenarios']}
    return [estimate_gold_value(states[result['name']],result)
            for result in data['exact'] if result['complete']]


def calibration_scenarios():
    states=[{'name':f'empty-r{turn}-g5','round':turn,'gold':5,'board':[None]*9} for turn in range(1,6)]
    states += [
        {'name':'three-tigers-r3-g5','round':3,'gold':5,'board':['神乐·琳','鬼狩·苍牙','雷兽·阿力']+[None]*6},
        {'name':'five-cards-r4-g5','round':4,'gold':5,'board':['神乐·琳','鬼狩·苍牙','雷兽·阿力','超威·阿力','修罗覆面']+[None]*4},
        {'name':'seven-cards-r5-g8','round':5,'gold':8,'board':['神乐·琳','鬼狩·苍牙','雷兽·阿力','超威·阿力','修罗覆面','赤芒','VVIP黑卡']+[None]*2}]
    return states


def recompute(seconds=60,progress=None):
    rows=[];runs=[];incomplete=[]
    for raw in calibration_scenarios():
        result=simulate(raw,profile='refresh_v1',seconds=seconds)
        runs.append({'state':raw,'result':result})
        if result['complete']:
            row=estimate_gold_value(raw,result);rows.append(row)
            if progress:progress(row)
        else:
            incomplete.append(raw['name'])
            if progress:progress({'name':raw['name'],'complete':False,'elapsed_s':result['elapsed_s']})
    return {'profile':'refresh_v1','method':'whole_pool_gain_per_actual_spent_coin',
            'complete_reference':not incomplete,'rows':rows,'incomplete':incomplete,'runs':runs,
            'limits':['数值是当前棋盘/回合/预算的组合平均效率，不是对刷新后可见5牌的精确机会成本。',
                      '相近空格数只作启发近似；相同空格但不同羁绊可能有不同价格。',
                      '未假设后续再买牌；不加入早100偏好、空位潜力和未激活羁绊分。']}
