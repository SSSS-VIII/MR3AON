"""Native collider targets and whole-episode split protection."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_yolo_data import annotations,build,category


def test_native_targets_use_colliders_and_skip_hidden_enemy_models():
    row={'role':{'colliders':[{'box':[170,210,190,250]}]},'objects':[
        {'name':'EnemySpider(Clone)','renderers':[{'box':[300,100,450,300]}],
         'colliders':[{'box':[340,200,362,222]}]},
        {'name':'EnemyHidePaw(Clone)','renderers':[], 'colliders':[{'box':[400,180,420,200]}]}]}
    assert annotations(row)==[(0,[170.,210.,190.,250.]),(1,[340.,200.,362.,222.])]
    assert category('EnemySpiderWeb')==4
    assert category('EnemyCurveCrow')==2
    assert category('EnemyDart2')==5


def test_data_builder_rejects_same_episode_across_splits_before_writing(tmp_path):
    episode=tmp_path/'one';out=tmp_path/'output'
    with pytest.raises(ValueError,match='disjoint'):
        build(out,[episode],[episode],tmp_path/'references')
    assert not out.exists()
