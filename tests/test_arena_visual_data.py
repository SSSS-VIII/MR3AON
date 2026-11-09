"""Frozen replay and annotation-purpose regressions with synthetic data only."""
import json
from pathlib import Path
import sys
import pytest
cv2=pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Track
from arena_vision_dataset import replay
from arena_yolo_audit import family,resource_name


def test_replay_freezes_mutable_tracks_before_future_label_alignment(tmp_path):
    rows=[]
    for i in range(2):
        name=f'{i}.png';cv2.imwrite(str(tmp_path/name),np.zeros((360,640,3),np.uint8))
        rows.append(dict(image=name,t=i*.1,objects=[]))
    (tmp_path/'labels.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in rows))
    class MutablePerception:
        def __init__(self):
            self.track=Track(1,Box(500,100,30,24),'eye_enemy',.93,0)
        def observe(self,image,t):
            self.track.box.x=500-100*t
            return dict(tracks=[self.track])
    result=list(replay(tmp_path,MutablePerception()))
    assert result[0][1]['tracks'][0].box.x==500
    assert result[1][1]['tracks'][0].box.x==490


def test_native_resource_identity_and_coarse_family_are_separate():
    assert resource_name('EnemyCurveCrow(Clone)(Clone)')=='enemycurvecrow'
    assert family('EnemyStraightBat')==family('EnemyCurveCrow')
    assert resource_name('EnemyStraightBat')!=resource_name('EnemyCurveCrow')
    assert family('EnemyPinball')!=family('EnemySpider')


def test_replay_uses_same_prediction_roi_as_precision_denominator(tmp_path):
    cv2.imwrite(str(tmp_path/'frame.png'),np.zeros((360,640,3),np.uint8))
    row=dict(image='frame.png',t=0,objects=[dict(id=7,type='EnemySpider',name='EnemySpider(Clone)',
        colliders=[dict(box=[590,100,620,124])])])
    (tmp_path/'labels.jsonl').write_text(json.dumps(row)+'\n')
    class OutsidePrediction:
        def observe(self,image,t):
            # This would match the visible native center at605 by distance, but
            # its own center620 is outside the prediction-counting ROI.
            return dict(tracks=[Track(1,Box(605,100,30,24),'spider',.93,t)])
    result=list(replay(tmp_path,OutsidePrediction()))
    assert result[0][2]and not result[0][3]
