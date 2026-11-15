"""场面相关的未触发被动估值；仅离线，不连接实例。"""
import pytest
from tools.intelligence_simulator.refresh import analyze_hand, hand_choices
from tools.intelligence_simulator.single_player import play
from tools.intelligence_simulator.model import simulate

LO='龙吟·洛青'
WATER='神乐·琳'
SILVER='雷羿·银枭'


def choice(raw, hand, names):
    return next(c for c in hand_choices(raw,hand,synergy=True)['choices']
                if sorted(c['cards'])==sorted(names))


def term(c,name):
    return next(t for t in c['synergy_details'] if t['card']==name)


def test_loqing_user_examples_and_round_decay():
    solo=choice({'round':1,'gold':3},[LO],[LO])
    assert solo['damage']==15 and 0<term(solo,LO)['value']<12
    together=choice({'round':1,'gold':3},[LO,WATER],[LO,WATER])
    assert term(together,LO)['value']>term(solo,LO)['value']
    assert together['board'].index(LO)//3==together['board'].index(WATER)//3
    late=choice({'round':2,'gold':3},[LO],[LO])
    assert late['damage']==12 and 0<term(late,LO)['value']<term(solo,LO)['value']
    progressed=choice({'round':2,'gold':3},[LO,WATER],[LO,WATER])
    assert term(progressed,LO)['value']>term(late,LO)['value']


def test_blocking_a_water_row_loses_existing_potential():
    raw={'round':2,'gold':4,'board':[LO,WATER,None,'炎魂·小黑','鬼狩·苍牙','雷兽·阿力','神炎·小椒',None,None]}
    safe=choice(raw,['赤芒'],['赤芒'])
    assert safe['board'][2] is None
    raw['board'][7:9]=['修罗覆面','VVIP黑卡']
    forced=choice(raw,['赤芒'],['赤芒'])
    assert term(forced,LO)['reason']=='row_blocked'
    assert forced['potential_gain']<0


def test_thunder_support_advances_existing_silver_and_dragon():
    for source in [SILVER,'雷龙']:
        raw={'round':2,'gold':2,'board':[source,'雷兽·阿力']+[None]*7}
        empty=choice(raw,['超威·阿力'],[])
        bought=choice(raw,['超威·阿力'],['超威·阿力'])
        assert term(empty,source)['progress']==2
        assert term(bought,source)['progress']==3
        assert term(bought,source)['value']>term(empty,source)['value']
        assert bought['potential_gain']>0


def test_late_tiger_progress_can_complete_multiple_cards_next_round():
    raw={'round':4,'gold':3,'board':['双焰·小椒','炎魂·小黑']+[None]*7}
    empty=choice(raw,[WATER],[])
    bought=choice(raw,[WATER],[WATER])
    assert term(bought,'双焰·小椒')['progress']==3
    assert term(bought,'双焰·小椒')['value']>term(empty,'双焰·小椒')['value']>=0
    assert term(bought,'双焰·小椒')['completion_by_round'][4]>0


def test_reference_probability_matches_small_pool_and_refresh_opportunity():
    board=[SILVER,'雷兽·阿力','雷龙']+[None]*6
    pool={'超威·阿力':1,'星闪·小椒':1,'猫太·老板娘':1,
          '樱火·茜':1,'寒绡·兮兰':1,WATER:1}
    # Five draws from six physical cards contain both two thunder cards in 4/6 cases.
    raw={'round':4,'gold':1,'board':board,'pool_override':pool}
    result=simulate(raw,profile='synergy_v2',max_purchases=0,trace_choices=True)
    silver=term(result['choices'][0],SILVER)
    assert silver['completion_by_round'][4]==pytest.approx(2/3)
    assert silver['value']==pytest.approx(4*2/3)
    raw.update(round=5,gold=4,refreshes=1,shop_slots=5)
    refreshed=simulate(raw,profile='synergy_v2',max_purchases=0,trace_choices=True)
    assert term(refreshed['choices'][0],SILVER)['value']==pytest.approx(4*2/3)
    raw['refreshes']=0
    final=simulate(raw,profile='synergy_v2',max_purchases=0,trace_choices=True)
    assert term(final['choices'][0],SILVER)['value']==0


def test_tiger_support_credits_existing_four_tiger_source():
    raw={'round':1,'gold':1,'board':['龙焰·小黑']+[None]*8}
    empty=choice(raw,[WATER],[])
    bought=choice(raw,[WATER],[WATER])
    assert term(bought,'龙焰·小黑')['value']>term(empty,'龙焰·小黑')['value']


def test_no_future_supply_space_or_time_means_no_latent_bonus():
    for raw in [
        {'round':1,'gold':2,'pool_override':{LO:1}},
        {'round':5,'gold':2},
        {'round':1,'gold':2,'board':[None,'赤芒','焚天','炎魂·小黑','鬼狩·苍牙','雷兽·阿力','神炎·小椒','轮回之戒','VVIP黑卡']},
    ]:
        c=choice(raw,[LO],[LO])
        assert c['synergy_potential']==0


def test_already_active_passives_are_real_damage_not_extra_potential():
    raw={'round':3,'gold':0,'board':[LO,WATER,'雪舞·琳',SILVER,'雷龙','雷兽·阿力','超威·阿力','星闪·小椒',None]}
    c=choice(raw,[],[])
    assert term(c,LO)['value']==term(c,SILVER)['value']==term(c,'雷龙')['value']==0
    assert term(c,LO)['reason']=='active'


def test_linear_growth_potential_uses_remaining_rounds_and_supply():
    for source in ['剑心·卫鲤','黑龙']:
        early=choice({'round':1,'gold':4},[source],[source])
        late=choice({'round':4,'gold':4},[source],[source])
        end=choice({'round':5,'gold':4},[source],[source])
        assert early['synergy_potential']>late['synergy_potential']>end['synergy_potential']==0
        unavailable=choice({'round':1,'gold':4,'pool_override':{source:1}},[source],[source])
        assert unavailable['synergy_potential']==0


def test_known_timed_effects_are_not_counted_twice():
    for source in ['极刃·血影','霜刃·伊鹤']:
        raw={'round':2,'gold':3}
        c=choice(raw,[source],[source])
        old=next(c for c in hand_choices(raw,[source])['choices'] if c['cards'])
        assert c['damage']==old['damage'] and c['synergy_potential']==0


def test_fixed7_score_separates_potential_from_real_damage():
    plan=analyze_hand({'round':1,'gold':5},[LO,WATER],synergy=True)
    c=plan['chosen']
    assert plan['coin_value']==7
    assert plan['score']==pytest.approx(c['damage']+c['synergy_potential']+7*c['valued_gold'])
    assert c['damage_gain']==c['existing_card_damage_gain']+c['new_card_damage']
    assert not any('lock' in a for a in plan['actions'])


def test_offline_game_actual_damage_never_contains_latent_points():
    for strategy in ['fixed7','synergy_v2']:
        game=play(2,strategy,None)
        assert sum(game['round_damage'])==game['total_damage']
        assert all(e['coin_value']==7 for r in game['trace'] for e in r['events'])
        assert game['rounds_played']<=5
