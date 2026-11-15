"""Earlier kills rank higher in regression reports; score and damage stay separate."""
from tools.intelligence_simulator.single_player import finish_score,aggregate


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
