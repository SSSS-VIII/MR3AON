"""第一版金币/刷新策略与单边回归：不连接设备，提前100仅用于验收。"""
from tools.intelligence_simulator.model import simulate
from tools.intelligence_simulator.refresh import (
    analyze_hand,build_reference_table,coin_reference,hand_choices,select_choice,
)
from tools.intelligence_simulator.single_player import aggregate,play


def test_complex_cards_are_plain_without_changing_their_base_attack():
    cat=simulate({'round':5,'gold':20,'board':['猫太·老板娘']+[None]*8,'pool_override':{}},profile='refresh_v1')
    assert cat['best_damage']==1
    ghost=simulate({'round':3,'gold':0,'board':['鬼斩·紫原','鬼斩胸甲','鬼斩臂甲','鬼斩头盔']+[None]*5,'pool_override':{}},profile='refresh_v1')
    assert ghost['instant_win_combinations']==0 and ghost['best_damage']==30
    ring=hand_choices({'round':4,'gold':2},['轮回之戒'])
    purchased=next(c for c in ring['choices'] if c['cards'])
    assert purchased['damage']==4 and purchased['extra_refreshes']==0


def test_buy_one_keep_gold_and_refresh_unbought_slot():
    plan=analyze_hand({'round':5,'gold':4},['怒鲤双生','轮回之戒'],3)
    assert plan['chosen']['cards']==['怒鲤双生']
    assert plan['chosen']['gold_left']==2 and plan['next_action']=='refresh'
    assert plan['replaceable_shop_slots']==1
    assert plan['actions'][0]['shop_slot']==0
    assert plan['latent_empty_cell_value']==plan['inactive_synergy_value']==0
    assert any(c['gold_left']==4 for c in plan['choices'])
    assert any(c['gold_left']==0 for c in plan['choices'])


def test_active_buff_gain_to_existing_cards_is_not_lost_or_counted_twice():
    raw={'round':5,'gold':2,'board':['怒鲤双生']+[None]*8}
    plan=analyze_hand(raw,['修罗覆面'],0)
    chosen=plan['chosen']
    assert chosen['existing_card_damage_gain']==2
    assert chosen['new_card_damage']==1 and chosen['damage_gain']==3
    assert plan['actions'][0]['cell'] in (1,3)  # 中心不相邻，不能因站位偏好牺牲真实伤害。


def test_temporary_buff_only_counts_actual_duration_not_empty_spaces():
    raw={'round':3,'gold':2,'board':['怒鲤双生']+[None]*8}
    chosen=analyze_hand(raw,['樱火·茜'],0)['chosen']
    assert chosen['existing_card_damage_gain']==6
    assert chosen['new_card_damage']==3 and chosen['damage_gain']==9
    raw['round']=5
    chosen=analyze_hand(raw,['樱火·茜'],0)['chosen']
    assert chosen['existing_card_damage_gain']==3 and chosen['new_card_damage']==1


def test_equal_damage_position_preferences_only_break_ties():
    mask=analyze_hand({'round':3,'gold':2},['修罗覆面'],0)
    assert mask['actions'][0]['cell']==4
    multiplier=analyze_hand({'round':4,'gold':3},['极刃·血影'],0)
    assert multiplier['actions'][0]['cell'] in (1,3,5,7)


def test_no_refresh_can_fill_purchased_empty_slots_or_spend_absent_gold():
    all_bought=analyze_hand({'round':5,'gold':4},['怒鲤双生'],0)
    assert all_bought['next_action']=='prepare' and all_bought['replaceable_shop_slots']==0
    no_refresh=analyze_hand({'round':5,'gold':4},['怒鲤双生','轮回之戒'],3,refreshes=0)
    assert no_refresh['next_action']=='prepare'
    empty=analyze_hand({'round':5,'gold':0},['怒鲤双生'],1)
    assert empty['actions']==[] and empty['next_action']=='prepare'


def test_single_card_reference_is_explicitly_limited_and_copy_weighted():
    raw={'round':1,'gold':2,'pool_override':{'怒鲤双生':2}}
    value=coin_reference(raw)
    assert value['median']==6 and value['eligible_copies']==2
    assert '非5槽' in value['method']
    mixed=coin_reference({'round':5,'gold':2,'pool_override':{'怒鲤双生':1,'轮回之戒':1}})
    assert mixed['median']==2.5  # 两个不同单位收益1与4，不能把下分位点当算术中位数。
    result=simulate({'gold':6},max_purchases=1,profile='refresh_v1')
    assert result['space']['combinations']==54 and result['space']['layouts']==478


def test_ranking_changes_with_coin_value_and_reports_breakpoints():
    plan=analyze_hand({'round':5,'gold':4},['怒鲤双生','轮回之戒'],3)
    aggressive=select_choice(plan['choices'],0)
    reserve=select_choice(plan['choices'],100)
    assert len(aggressive['cards'])==2 and reserve['cards']==[]
    assert any(row['cards']==['怒鲤双生'] for row in plan['frontier'])


def test_single_player_fixed_seed_and_early_stop_contract():
    reference=build_reference_table()
    first=play(1,'v1',reference);again=play(1,'v1',reference)
    assert first['round_damage']==again['round_damage']
    assert first['trace']==again['trace']
    assert first['reached_100']==(first['total_damage']>=100)
    assert first['rounds_played']<=5
    if first['reached_100']:
        assert sum(first['round_damage'][:-1])<100
    previous=None
    for r in first['trace']:
        assert r['gold_at_end']>=0 and len(r['events'])<=2
        if previous:
            assert r['events'][0]['gold_before']==previous['gold_at_end']+3+(2 if previous['bought']==0 else 1 if previous['bought']==1 else 0)
        if len(r['events'])==2:
            a,b=r['events']
            assert len(b['hand'])==len(a['hand'])-len(a['bought'])
        previous=r
    early=play(4,'v1',reference)
    assert early['hit_round']==4 and early['rounds_played']==4
    assert sum(early['round_damage'][:-1])<100<=early['total_damage']


def test_test_metrics_separate_early_success_from_raw_overkill():
    games=[{'reached_100':True,'hit_round':3,'total_damage':105,'decision_ms':[1],
            'partial_purchase_refreshes':1,'zero_purchase_refreshes':0},
           {'reached_100':False,'hit_round':None,'total_damage':90,'decision_ms':[2],
            'partial_purchase_refreshes':0,'zero_purchase_refreshes':1}]
    report=aggregate(games)
    assert report['reach_100_rate']==.5 and report['hit_round_counts']['3']==1
    assert report['mean_damage']==97.5
