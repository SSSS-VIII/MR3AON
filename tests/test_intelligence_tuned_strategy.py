"""刷新前后机会不同，最后一轮的剩余金币不能再当作伤害。"""
from copy import deepcopy
import pytest
from tools.intelligence_simulator.tuned import DEFAULT_POLICY,analyze_tuned


def policy(**changes):
    p=deepcopy(DEFAULT_POLICY);p.update(changes);return p


def test_before_refresh_saves_money_but_after_refresh_spends_in_last_round():
    p=policy(gold_before_refresh=[6]*5,gold_after_refresh=[1,1,1,1,0])
    raw={'round':5,'gold':2}
    before=analyze_tuned(raw,['猫太·老板娘'],1,policy=p)
    after=analyze_tuned(raw,['猫太·老板娘'],0,policy=p)
    assert before['actions']==[] and before['next_action']=='refresh'
    assert before['coin_value']==6 and before['gold_phase']=='before_refresh'
    assert len(after['actions'])==1 and after['next_action']=='prepare'
    assert after['coin_value']==0 and after['gold_phase']=='after_refresh'


def test_buying_all_slots_cannot_claim_value_from_another_hand():
    p=policy(gold_before_refresh=[6]*5,gold_after_refresh=[1,1,1,1,0])
    plan=analyze_tuned({'round':5,'gold':8},['夜叉·隼白'],1,policy=p)
    assert plan['actions'] and plan['next_action']=='prepare'
    assert plan['gold_phase']=='after_refresh' and plan['coin_value']==0


def test_immediate_finish_preferred_to_more_damage_after_game_would_end():
    names=['樱火·茜','寒绡·兮兰','乘霄·戌时','月晖·小夜','冰羽·兮兰','风铭·戌时','奔雷·银枭','猫太·老板娘']
    raw={'round':4,'gold':3,'board':[{'name':n,'entered_round':1} for n in names]+[None]}
    hand=['怒鲤双生','极刃·血影']
    greedy=analyze_tuned(raw,hand,0,policy=policy(prioritize_finish=False,lookahead_weight=0),cumulative_damage=85)
    finish=analyze_tuned(raw,hand,0,policy=policy(prioritize_finish=True),cumulative_damage=85)
    assert greedy['chosen']['cards']==['极刃·血影']
    assert finish['chosen']['cards']==['怒鲤双生']
    assert finish['chosen']['damage']<greedy['chosen']['damage']
    assert 85+finish['chosen']['round_damage'][3]>=100


def test_policy_validation_and_no_mutation():
    p=policy();raw={'round':5,'gold':2};saved=deepcopy(p)
    analyze_tuned(raw,['猫太·老板娘'],0,policy=p)
    assert p==saved and raw=={'round':5,'gold':2}
    for bad in [policy(gold_after_refresh=[1]*5),policy(income_weight=float('nan'))]:
        with pytest.raises(ValueError):analyze_tuned(raw,[],policy=bad)


def test_when_both_options_finish_maximize_damage_now():
    names=['樱火·茜','寒绡·兮兰','乘霄·戌时','月晖·小夜','冰羽·兮兰','风铭·戌时','奔雷·银枭','猫太·老板娘']
    raw={'round':4,'gold':3,'board':[{'name':n,'entered_round':1} for n in names]+[None]}
    chosen=analyze_tuned(raw,['怒鲤双生','极刃·血影'],0,cumulative_damage=90)['chosen']
    assert chosen['cards']==['怒鲤双生'] and chosen['finishing']
    assert chosen['round_damage'][3]==16  # 血影本回合14，虽第五回合更高也不再计入结束后的收益。


def test_full_five_rounds_does_not_redefine_actual_stop_mean():
    from tools.intelligence_simulator.single_player import aggregate,play,target_checks
    short=play(4,'tuned');full=play(4,'tuned',stop_at_100=False)
    assert short['hit_round']==full['hit_round']
    assert short['total_damage']==full['actual_stop_damage']
    assert short['trace']==full['trace'][:short['rounds_played']]
    report=aggregate([full])
    assert report['mean_damage']==short['total_damage']
    assert report['mean_five_round_damage']==full['total_damage']
    summary={'mean_damage':125,'mean_five_round_damage':135,'reach_100_rate':.995,'four_round_kill_rate':.25}
    assert not target_checks(summary)['all_met']
    assert target_checks(summary,five_rounds=True)['all_met']


def test_no_future_inventory_means_no_empty_slot_buff_forecast():
    from tools.intelligence_simulator.refresh import hand_choices
    raw={'round':1,'gold':2,'pool_override':{'修罗覆面':1}}
    result=hand_choices(raw,['修罗覆面'],synergy=True,heuristics={'aura_weight':2})
    c=next(c for c in result['choices'] if c['cards'])
    assert c['synergy_potential']==0


def test_expired_temporary_buffs_cannot_support_future_empty_cells():
    from tools.intelligence_simulator.refresh import hand_choices
    raw={'round':3,'gold':0,'board':[{'name':'冰羽·兮兰','entered_round':1}]+[None]*8}
    result=hand_choices(raw,[],synergy=True,heuristics={'aura_weight':2})
    assert result['choices'][0]['synergy_potential']==0


def test_empty_slot_forecast_is_distinct_from_an_active_bonus():
    from tools.intelligence_simulator.refresh import hand_choices
    result=hand_choices({'round':1,'gold':2},['修罗覆面'],synergy=True,heuristics={'aura_weight':2})
    c=next(c for c in result['choices'] if c['cards'])
    assert c['damage']==5 and c['synergy_potential']>0
    assert c['synergy_details'][0]['reason']=='empty_slot_forecast'
    assert c['synergy_details'][0]['confidence'] is None
