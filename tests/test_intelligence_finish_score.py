"""Earlier kills dominate later overkill; neither reporting nor planning fakes damage."""
import pytest
from tools.intelligence_simulator.single_player import finish_score,aggregate
from tools.intelligence_simulator.tuned import analyze_tuned,resolve_policy


def test_earlier_win_always_beats_later_overkill():
    assert finish_score(4,100)>finish_score(5,10000)
    assert finish_score(3,100)>finish_score(4,10000)
    assert finish_score(5,100)>finish_score(None,99)
    assert finish_score(4,110)==210


def test_report_score_never_relabels_actual_damage():
    games=[dict(hit_round=4,reached_100=True,total_damage=108,actual_stop_damage=108,
                five_round_damage=150,decision_ms=[1],partial_purchase_refreshes=0,zero_purchase_refreshes=0)]
    report=aggregate(games)
    assert report['mean_finish_score']==208
    assert report['mean_damage']==108 and report['mean_five_round_damage']==150


@pytest.mark.parametrize(('turn','expected'),[(3,201),(4,101)])
def test_native_research_continuation_stops_on_first_kill(turn,expected):
    names=['樱火·茜','寒绡·兮兰','乘霄·戌时','月晖·小夜','冰羽·兮兰','风铭·戌时','奔雷·银枭','猫太·老板娘']
    raw={'round':turn,'gold':0,'board':[{'name':n,'entered_round':1} for n in names]+[None],'pool_override':{}}
    result=analyze_tuned(raw,[],0,cumulative_damage=85,policy={'rollout_objective':'finish','rollout_samples':2})
    assert result['chosen']['lookahead_score']==expected  # Eight attack each turn; first kill is exactly 101.
    assert result['forecast']['inventory_valid']


def test_research_cannot_disable_the_early_kill_guard():
    with pytest.raises(ValueError):resolve_policy({'rollout_objective':'finish','prioritize_finish':False})
    assert resolve_policy()['rollout_objective']=='damage'  # Deployed defaults stay fixed during research.


def test_no_mixing_score_bands_with_damage_objective():
    for override in [{'lookahead_weight':.5},{'lookahead_mode':'single'}]:
        with pytest.raises(ValueError):resolve_policy(dict(rollout_objective='finish',**override))
    assert resolve_policy({'rollout_objective':'finish'})['rollout_early_bonus']==0
    for override in [{'rollout_beam_diversity':True,'lookahead_mode':'single'},
                     {'rollout_reliability_first':True}]:
        with pytest.raises(ValueError):resolve_policy(override)


def test_reliability_guard_rejects_a_fast_but_riskier_prediction():
    from tools.intelligence_simulator.tuned import select_tuned_choice
    safe=dict(finishing=False,predicted_failure_rate=0,score=120,damage=20,gold_left=0,position_priority=0)
    risky=dict(safe,predicted_failure_rate=.1,score=250)
    policy=resolve_policy({'rollout_objective':'finish','rollout_reliability_first':True})
    assert select_tuned_choice([risky,safe],policy) is safe
    immediate=dict(risky,finishing=True)
    assert select_tuned_choice([immediate,safe],policy) is immediate


def test_diverse_beam_is_optional_and_preserves_physical_inventory():
    policy={'rollout_beam_diversity':True,'rollout_samples':2,'rollout_width':4,'rollout_candidates':4}
    result=analyze_tuned({'round':2,'gold':7},['神乐·琳','龙吟·洛青','怒鲤双生','VVIP黑卡'],policy=policy)
    assert result['forecast']['beam_diversity']
    assert 2<=result['forecast']['max_beam_cardsets']<=4
    assert result['forecast']['inventory_valid']
    assert not resolve_policy()['rollout_beam_diversity']
