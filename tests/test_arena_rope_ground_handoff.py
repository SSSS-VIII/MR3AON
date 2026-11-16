"""A finite rope end must not hide the visible adjoining landing surface."""
from pathlib import Path
import json,sys
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_support import VisualSupports
from arena_vision import Box,Perception,can_air_down
from arena_projection import SCALE
import arena_motion as motion


FIXTURE=json.loads((Path(__file__).parent/'fixtures/arena-rope-ground-handoff.json').read_text())


def replay(enabled,change=None):
    supports=VisualSupports(rope_ground_handoff=enabled);supports.mode=FIXTURE['initial_mode']
    for index,f in enumerate(FIXTURE['frames']):
        segments=[dict(s)for s in f['segments']]
        if index==1 and change is not None:segments=change(segments)
        p=Box(**f['player']);result=supports.observe(segments,p,f['time'])
    return supports,result,p


def test_actual_joined_ground_becomes_available_after_the_finite_rope_end():
    old,before,_=replay(False)
    new,after,p=replay(True)
    assert old.mode=='rope'and before['rope']is None and before['terrain']is None
    assert new.mode=='ground'and after['rope']is None
    assert after['terrain']['source']=='neural_segments'
    assert after['terrain']['at_player']
    assert len(after['terrain']['segments'])==1


def test_current_context_change_does_not_certify_landing_or_reset_jumps():
    supports,surface,p=replay(True)
    stamp=FIXTURE['frames'][-1]['time'];perception=Perception();perception.visual_role=True
    perception.jump_count=1;perception.active_motion=dict(name='jump1',started=stamp-.2)
    perception.motion_origin=dict(scale=SCALE,stand_h=motion.DATA['stand_height']*SCALE)
    result=perception._finish(np.zeros((360,640,3),np.uint8),stamp,p,[],support_observation=surface)
    result.update(scale_px=SCALE,stand_h=motion.DATA['stand_height']*SCALE)
    assert result['phase'].startswith('jump1')and result['jumps']==1
    assert not result['ground_contact_observed']
    assert can_air_down(result)


def modified(key,value):
    def change(segments):
        segments[0 if key.startswith('rope:')else 1][key.split(':')[-1]]=value
        return segments
    return change


@pytest.mark.parametrize('change',[
    modified('rope:right_clipped',True),
    modified('rope:confidence',.5),
    modified('rope:b',(230,259)),
    modified('kind','floating_platform'),
    modified('confidence',.2),
    modified('a',(250,261)),
    modified('a',(0,261)),
    modified('a',(162,320)),
    lambda segments:segments[1:],
    lambda segments:segments[:1],
    lambda segments:segments+[dict(kind='rope',a=(350,259),b=(550,259),confidence=.95)],
])
def test_uncertain_rope_or_unconnected_ground_does_not_change_context(change):
    supports,result,p=replay(True,change)
    assert supports.mode=='rope'
    assert result['terrain']is None


def test_normal_rope_over_ground_is_not_a_finite_end_transition():
    supports=VisualSupports(rope_ground_handoff=True)
    rope=dict(kind='rope',a=(0,250),b=(640,250),confidence=.95)
    ground=dict(kind='platform',a=(0,310),b=(640,310),confidence=.95)
    result=supports.observe([rope,ground],Box(180,200,16,37),1.)
    assert result['mode']=='rope'and result['terrain']is None
