"""全池金币估价必须扣实际花费、处理张数与空购买，不混用单张或截断数据。"""
import pytest

from tools.intelligence_simulator.gold_value import estimate_gold_value,spending_distribution
from tools.intelligence_simulator.model import simulate
from tools.intelligence_simulator.refresh import lookup_coin_value


def test_gold_price_uses_actual_spending_not_the_budget():
    raw={'round':1,'gold':4,'pool_override':{'怒鲤双生':2}}
    result=simulate(raw,profile='refresh_v1')
    price=estimate_gold_value(raw,result)
    assert price['physical_subsets']==4
    assert price['mean_actual_spent']==2 and price['mean_gain']==12
    assert price['gold_value']==6  # 不能用预算4当分母得到3。
    assert price['weighted_gain_sum']==48 and price['weighted_spent_sum']==8
    assert spending_distribution(raw)==[
        {'spent':0,'unique_combinations':1,'physical_subsets':1},
        {'spent':2,'unique_combinations':1,'physical_subsets':2},
        {'spent':4,'unique_combinations':1,'physical_subsets':1}]


def test_old_card_buff_damage_is_included_in_pool_gold_price():
    raw={'round':5,'gold':2,'board':['怒鲤双生']+[None]*8,'pool_override':{'修罗覆面':1}}
    price=estimate_gold_value(raw,simulate(raw,profile='refresh_v1'))
    assert price['gold_value']==1.5  # 面具自身1＋原火牌被强化2，除以2金币。


def test_zero_spend_has_zero_price_instead_of_dividing_by_zero():
    raw={'round':5,'gold':0}
    price=estimate_gold_value(raw,simulate(raw,profile='refresh_v1'))
    assert price['gold_value']==0 and price['weighted_spent_sum']==0


def test_sampling_truncation_and_single_card_results_cannot_be_pool_prices():
    raw={'round':1,'gold':5}
    with pytest.raises(ValueError,match='全池'):
        estimate_gold_value(raw,simulate(raw,max_layouts=1))
    with pytest.raises(ValueError,match='单张'):
        estimate_gold_value(raw,simulate(raw,max_purchases=1))
    with pytest.raises(ValueError,match='全池'):
        estimate_gold_value(raw,simulate(raw,samples=1,max_layouts=1))


def test_new_reference_table_is_explicit_and_old_median_table_still_works():
    table={'method':'whole_pool_gain_per_actual_spent_coin','profile':'refresh_v1','complete_reference':True,
           'rows':[{'round':3,'empty':6,'gold_value':5.7}]}
    assert lookup_coin_value(table,3,5)==5.7
    assert lookup_coin_value(table,3,0)==0
    table['complete_reference']=False
    with pytest.raises(ValueError,match='截断'):lookup_coin_value(table,3,5)
    with pytest.raises(ValueError,match='截断'):lookup_coin_value({'rows':[],'complete_reference':False},3,5)
    assert lookup_coin_value({'rows':[{'round':3,'empty':6,'median':3.5}]},3,5)==3.5
