"""An expected jump above the image differs from an unexplained missing role."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Perception
from arena_obb_detector import missing_role_prediction
import numpy as np


def airborne(y=-40):
    return dict(time=1.,player=Box(180,y,8,8),phase='jump2_rising',jumps=2,
                motion=dict(name='jump2',started=.95),rope=None,terrain=None,scale_px=40.,
                stand_w=16.,stand_h=37.44,vy=-200.)


def test_expected_jump_above_view_survives_the_short_occlusion_lease():
    p,reason=missing_role_prediction(airborne(),1.1,.3)
    assert p is not None and p.y+p.h<70 and reason=='expected_above_view'
    assert missing_role_prediction(airborne(y=200),1.1,.3)==(None,None)
    assert missing_role_prediction(airborne(),1.1,.7)==(None,None)
    uncommanded=dict(airborne(),motion=None)
    assert missing_role_prediction(uncommanded,1.1,.3)==(None,None)


def test_extrapolated_jump_contact_is_not_a_real_landing_acknowledgement():
    actor=Perception();actor.visual_role=True
    start=dict(airborne(y=100),phase='ground',jumps=0,motion=None)
    actor.action('jump',1.,start)
    support=dict(mode='ground',rope=None,terrain=dict(y=253,at_player=True),
                 segments=[],tracking_reference=(0.,0.))
    p=Box(172,211.28,16,37.44)
    predicted=actor._finish(np.zeros((360,640,3),np.uint8),2.,p,[],
                            support_observation=support,player_observed=False)
    assert predicted['motion']is not None and predicted['phase']=='jump1_falling'
    actual=actor._finish(np.zeros((360,640,3),np.uint8),2.025,p,[],support_observation=support)
    assert actual['motion']is None and actual['phase']=='ground'
