"""Starting at a later native board cannot count that entry as completion."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_visual_runner import evaluation_status,evaluation_goal_reached


def test_two_boards_from_position_four_require_entry_to_position_six():
    initial=dict(stageIndex=3,health=5000,damage=0,minHealth=5000)
    assert evaluation_status(initial,initial,5)=='duration'
    assert evaluation_status(initial,dict(initial,stageIndex=4),5)=='duration'
    assert evaluation_status(initial,dict(initial,stageIndex=5),5)=='passed'
    assert evaluation_status(initial,dict(initial,stageIndex=5,damage=120),5)=='damage'


def test_last_normal_board_finishes_when_the_native_boss_map_restarts_its_index():
    initial=dict(stageIndex=9,stageID=51091,stageCount=10,map=41,health=5000,damage=0,minHealth=5000)
    assert not evaluation_goal_reached(initial,initial,10)
    boss=dict(initial,map=2,stageIndex=0,stageID=130)
    assert evaluation_goal_reached(initial,boss,10)
    assert evaluation_status(initial,boss,10)=='passed'
    assert evaluation_status(initial,dict(boss,damage=250,minHealth=4750),10)=='damage'


def test_map_transition_cannot_complete_boards_beyond_the_original_map():
    initial=dict(stageIndex=9,stageCount=10,map=41,health=5000,damage=0,minHealth=5000)
    assert not evaluation_goal_reached(initial,dict(initial,map=2,stageIndex=0),11)
    assert not evaluation_goal_reached(initial,dict(initial,stageID=0),10)


def test_unknown_map_count_does_not_treat_an_index_reset_as_success():
    initial=dict(stageIndex=9,map=41,health=5000,damage=0,minHealth=5000)
    assert not evaluation_goal_reached(initial,dict(initial,map=2,stageIndex=0),10)
