"""离线规则/张数/统计正确性；不导入或连接Maa、ADB、实例运行层。"""
import math

import pytest

from tools.intelligence_simulator.model import (
    BY_NAME, CARDS, count_space, histogram_summary, prepare_state,
    sample_combinations, simulate,
)


def state(turn=5, gold=0, board=None, pool=None):
    return {'round': turn, 'gold': gold, 'board': board or [None]*9,
            'pool_override': pool or {}}


def run(raw, **kwargs):
    return simulate(raw, seconds=5, **kwargs)


def test_catalog_copy_counts_and_effects_are_complete():
    assert len(CARDS)==53 and sum(c['copies'] for c in CARDS)==81
    assert len(BY_NAME)==53
    assert [sum(c['copies'] for c in CARDS if c['category']==i) for i in range(5)]==[34,18,20,4,5]
    assert all(c['effect']!='plain' or c['category']==4 for c in CARDS)


def test_copy_weighting_and_indistinguishable_placement_counts():
    raw=state(turn=1,gold=4,pool={'怒鲤双生':2})
    space=count_space(prepare_state(raw))
    assert space=={'combinations':3,'physical_subsets':4,'layouts':46,'includes_pass':True}
    result=run(raw)
    assert result['layouts']==46 and result['complete']
    # 两张相同牌不因交换实体身份而多算落位。
    assert result['statistics']['unique_combinations']['damage_gain']['mean']==12
    assert result['statistics']['physical_subsets']['damage_gain']['mean']==12


def test_entry_damage_does_not_repeat_in_later_rounds():
    new=run(state(turn=1,gold=2,pool={'怒鲤双生':1}))
    assert new['best_damage']==12  # 五回合各1攻，仅入场一次+7。
    assert new['best_round_damage']==[8,1,1,1,1]
    old=run(state(turn=3,board=['怒鲤双生']+[None]*8))
    assert old['baseline_damage']==3 and old['best_round_damage']==[0,0,1,1,1]
    unweighted=run(state(turn=1,gold=2,pool={'怒鲤双生':2}))
    assert unweighted['statistics']['unique_combinations']['damage_gain']['mean']==6
    assert unweighted['statistics']['physical_subsets']['damage_gain']['mean']==8


def test_mask_only_buff_four_orthogonal_neighbors():
    board=['怒鲤双生','鬼斩胸甲','丛云之霜雨','鬼斩臂甲',None,
           '鬼斩头盔','巨阙·缚日','破云','封渊']
    result=run(state(gold=2,board=board,pool={'修罗覆面':1}))
    assert result['best_damage']-result['baseline_damage']==5  # 自身1+四邻各1；两个火牌都在斜角。


def test_row_and_column_entry_weapons_use_different_sums():
    board=['怒鲤双生','丛云之霜雨','破云','鬼斩胸甲',None,
           '鬼斩臂甲','巨阙·缚日','封渊','鬼斩头盔']
    row=run(state(gold=2,board=board,pool={'赤芒':1}))
    column=run(state(gold=2,board=board,pool={'焚天':1}))
    assert row['best_damage']-row['baseline_damage']==9
    assert column['best_damage']-column['baseline_damage']==6


def test_four_tigers_include_the_buff_source_and_duplicate_character_variants():
    board=['神乐·琳','鬼狩·苍牙','超威·阿力','雷兽·阿力']+[None]*5
    result=run(state(turn=4,board=board))
    assert result['statistics']['unique_combinations']['total_damage']['mean']==28
    assert result['statistics']['unique_combinations']['damage_gain']['mean']==0
    assert result['baseline_damage']==28  # 4+4+2+4，每回合14，剩两回合。


def test_temporary_buff_expires_after_two_rounds():
    board=['樱火·茜',None,None,'怒鲤双生']+[None]*5
    early=run(state(turn=1,board=board))
    assert early['best_round_damage']==[12,5,2,2,2]
    late=run(state(turn=3,board=board))
    assert late['baseline_damage']==6


def test_spending_gold_can_reduce_fifth_round_cat_damage():
    result=run(state(turn=4,gold=2,board=['猫太·老板娘']+[None]*8,pool={'VVIP黑卡':1}))
    assert result['baseline_damage']==30
    assert result['statistics']['unique_combinations']['damage_gain']['min']==-2
    assert result['statistics']['unique_combinations']['damage_gain']['mean']==-1
    assert result['best_combo']==[]


def test_direct_victory_is_not_replaced_with_fake_infinite_damage():
    result=run(state(turn=3,board=['鬼斩·紫原','鬼斩胸甲','鬼斩臂甲','鬼斩头盔']+[None]*5))
    assert result['instant_win_combinations']==1 and result['best_damage']==30


def test_inventory_excludes_only_owned_and_explicitly_known_cards():
    raw={'round':3,'gold':2,'board':['神乐·琳']+[None]*8,'known_unavailable':{'怒鲤双生':1}}
    parsed=prepare_state(raw)
    assert parsed['pool'][BY_NAME['神乐·琳']['id']]==0
    assert parsed['pool'][BY_NAME['怒鲤双生']['id']]==1
    assert sum(parsed['pool'])==79
    with pytest.raises(ValueError,match='超过'):
        prepare_state({'board':['神乐·琳']*2+[None]*7})
    with pytest.raises(ValueError):
        prepare_state(state(turn=2,board=[{'name':'神乐·琳','entered_round':3}]+[None]*8))


def test_exact_uniform_subset_sampling_accounts_for_copy_counts():
    parsed=prepare_state(state(gold=2,pool={'怒鲤双生':2}))
    unique=sample_combinations(parsed,4000,7,False)
    physical=sample_combinations(parsed,4000,7,True)
    assert abs(sum(bool(c) for c in unique)/4000-.5)<.03
    assert abs(sum(bool(c) for c in physical)/4000-2/3)<.03
    assert sample_combinations(parsed,10,7,True)==physical[:10]
    assert all(len(c)<=1 for c in physical)


def test_budget_exhaustion_never_labels_a_prefix_as_pool_statistics():
    result=run({'round':1,'gold':5},max_layouts=1)
    assert result['complete'] is False and result['coverage']<1
    assert 'statistics' not in result and 'sample_estimate' not in result
    assert 'partial_prefix_statistics_not_pool_estimate' in result


def test_weighted_median_handles_even_and_odd_populations():
    assert histogram_summary([[0,1,2],[12,1,1]],1)['median']==6
    assert histogram_summary([[0,1,2],[12,1,1]],2)['median']==0
    assert histogram_summary([],1) is None


def test_sampling_is_labelled_estimate_not_complete_enumeration():
    result=run(state(gold=2,pool={'怒鲤双生':2}),samples=300,seed=19,physical_sampling=True)
    assert result['mode']=='sample' and 'statistics' not in result
    assert result['sample_estimate']['distribution']=='physical_subsets'
    assert result['sample_estimate']['sampled_distribution']['total_damage']['count']==300
