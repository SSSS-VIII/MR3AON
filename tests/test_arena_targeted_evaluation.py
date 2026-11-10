"""Starting at a later native board cannot count that entry as completion."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_visual_runner import evaluation_status


def test_two_boards_from_position_four_require_entry_to_position_six():
    initial=dict(stageIndex=3,health=5000,damage=0,minHealth=5000)
    assert evaluation_status(initial,initial,5)=='duration'
    assert evaluation_status(initial,dict(initial,stageIndex=4),5)=='duration'
    assert evaluation_status(initial,dict(initial,stageIndex=5),5)=='passed'
    assert evaluation_status(initial,dict(initial,stageIndex=5,damage=120),5)=='damage'
