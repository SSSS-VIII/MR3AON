"""独立未知余池推演：精确小池期望、回合边界、预算与张数守恒。"""
import pytest
from tools.intelligence_simulator.tuned import analyze_tuned


def single(**changes):
    return dict(lookahead_mode='single',lookahead_weight=1,lookahead_gold_scale=0,**changes)


def test_exact_best_of_one_in_two_card_physical_pool():
    raw={'round':5,'gold':2,'pool_override':{'猫太·老板娘':1,'怒鲤双生':1}}
    result=analyze_tuned(raw,['猫太·老板娘'],1,policy=single())
    assert result['next_action']=='refresh' and result['actions']==[]
    # 1张下一手：白板老板娘1点、怒鲤双生8点，各一份。不是偷看真实下一张。
    assert result['chosen']['lookahead_score']==pytest.approx(4.5)
    assert result['forecast']['complete']


def test_next_round_does_not_repeat_last_round_weapon_entry_damage():
    raw={'round':4,'gold':0,'board':[{'name':'怒鲤双生','entered_round':4}]+[None]*8,
         'pool_override':{'猫太·老板娘':1}}
    result=analyze_tuned(raw,[],0,policy=single())
    assert result['chosen']['lookahead_score']==10  # 本轮8，次轮旧武器1＋新角色1。


def test_next_round_income_counts_prior_stage_purchase_and_black_card():
    raw={'round':4,'gold':0,'board':[{'name':'VVIP黑卡','entered_round':4}]+[None]*8,
         'pool_override':{'夜叉·隼白':1}}
    result=analyze_tuned(raw,[],0,policy=single())
    # 本回合已经买过1张，下轮3+少买奖励1+黑卡收入1=5，买不起6金隼白。
    assert result['chosen']['lookahead_score']==2


def test_rollout_reproducible_and_physical_inventory_conserved():
    raw={'round':2,'gold':8,'board':[{'name':'修罗覆面','entered_round':1}]+[None]*8}
    hand=['怒鲤双生','怒鲤双生','龙吟·洛青','VVIP黑卡']
    policy=dict(lookahead_mode='rollout',lookahead_weight=1,rollout_samples=2,rollout_width=4,rollout_candidates=4)
    first=analyze_tuned(raw,hand,1,policy=policy);again=analyze_tuned(raw,hand,1,policy=policy)
    assert first['actions']==again['actions'] and first['score']==again['score']
    assert first['forecast']['complete'] and first['forecast']['inventory_valid']
    assert first['forecast']['samples_completed']==2
    assert first['forecast']['layouts']>0


def test_budget_before_any_full_batch_falls_back_without_prefix_bias():
    raw={'round':1,'gold':5};hand=['龙吟·洛青','神乐·琳','怒鲤双生']
    old=analyze_tuned(raw,hand,policy={'lookahead_weight':0})
    limited=analyze_tuned(raw,hand,policy=dict(lookahead_mode='rollout',lookahead_weight=1,lookahead_seconds=1e-12))
    assert limited['forecast']['samples_completed']==0
    assert not limited['forecast']['complete']
    assert limited['actions']==old['actions'] and limited['score']==old['score']


def test_no_draw_remains_after_last_refresh():
    result=analyze_tuned({'round':5,'gold':2},['猫太·老板娘'],0,policy=single())
    assert result['forecast']['skipped']=='no_remaining_draw'
    assert result['actions'] and result['chosen']['coin_value']==0
