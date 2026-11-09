"""Native collider targets and whole-episode split protection."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_yolo_data import annotations,build,category,MissingControllerState


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


@pytest.mark.parametrize('native,expected',[('stay: 2',2),('ready: 3',6),('rushToNinja: 4',7)])
def test_native_crow_fsm_supervises_standard_detector_state_classes(native,expected):
    row={'role':{'colliders':[]},'objects':[dict(type='EnemyStraightBat',name='EnemyStraightCrow(Clone)',
         colliders=[dict(box=[300,200,330,230])],renderers=[{}],controller={'_currState':native})]}
    assert annotations(row,states=True)[0][0]==expected
    assert annotations(row)[0][0]==2  # Existing six-class data stays compatible.
    row['objects'][0].pop('controller')
    with pytest.raises(MissingControllerState):annotations(row,states=True)
    row['objects'][0]['dead']=True
    assert annotations(row,states=True)==[]


def test_state_score_distinguishes_found_body_from_correct_attack_phase():
    from arena_yolo_score import match_boxes
    truth=[(6,[300,200,330,230])]
    predicted=[(7,[300,200,330,230],.9),(7,[301,200,331,230],.8)]
    assert match_boxes(truth,predicted)==[]
    assert len(match_boxes(truth,predicted,parent=True))==1
