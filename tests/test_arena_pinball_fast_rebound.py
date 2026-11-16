"""Original future motion checks for a strong visually observed rebound."""
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
import json
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Track,Tracker,Detection
from arena_pinball_impulse import refresh_fast_rebound
from arena_projection import SCALE

DATA=json.loads((Path(__file__).parent/'fixtures/arena-pinball-fast-rebound.json').read_text())


def restore(case,enabled=True):
    kw={k:deepcopy(v)for k,v in case['track'].items()if k in{f.name for f in fields(Track)}}
    kw['box']=Box(**kw['box']);track=Track(**kw);track.pinball_fast_rebound=enabled
    return track


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['episode'])
def test_real_reversal_corrects_future_motion_without_native_parameters(case):
    track=restore(case);original=restore(case);box=track.box
    assert refresh_fast_rebound(track,SCALE)
    assert track.box==box and track.vx==original.vx and track.reference==original.reference
    assert track.history==original.history and track.ballistic
    for expected in case['future']:
        dt=expected['horizon'];actual=expected['native_delta']
        old=original.future(dt).center[1]-box.center[1]-actual
        new=track.future(dt).center[1]-box.center[1]-actual
        assert abs(new)<abs(old)and abs(new)<6


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['episode'])
def test_disabled_default_preserves_the_original_prediction(case):
    track=restore(case,False);before=deepcopy(vars(track))
    assert not refresh_fast_rebound(track,SCALE)
    assert vars(track)==before


@pytest.mark.parametrize('change',['floor_missing','floor_moving','far_from_floor','weak','not_pinball','bad_clock','nonfinite'])
def test_missing_or_contradictory_evidence_keeps_the_previous_fit(change):
    track=restore(DATA['cases'][0])
    if change=='floor_missing':track.floor_y=None
    elif change=='floor_moving':track.floor_vy=20.
    elif change=='far_from_floor':track.floor_y+=50
    elif change=='weak':track.confidence=.6
    elif change=='not_pinball':track.kind='spider'
    elif change=='bad_clock':track.history[-1][0]=track.history[-2][0]
    else:track.history[-1][2]=float('inf')
    old=(track.box,track.vy,track.rebound_speed,track.ballistic)
    assert not refresh_fast_rebound(track,SCALE)
    assert (track.box,track.vy,track.rebound_speed,track.ballistic)==old


def test_normal_impulse_and_mature_ascent_are_not_reinitialized():
    track=restore(DATA['cases'][0]);previous=track.history[-2]
    track.history[-1][2]=previous[2]-4*SCALE*(track.history[-1][0]-previous[0])
    assert not refresh_fast_rebound(track,SCALE)
    track=restore(DATA['cases'][0]);last=track.history[-1]
    track.history.extend([[last[0]+.06,last[1],last[2]-20],
                          [last[0]+.12,last[1],last[2]-39]])
    assert not refresh_fast_rebound(track,SCALE)


def test_live_update_hook_and_tracker_flag_apply_only_to_pinballs():
    case=DATA['cases'][0];track=restore(case);last=track.history.pop();track.observations-=1
    track.seen=track.history[-1][0]
    incoming=Detection(track.box,'pinball',track.confidence)
    floor_y=track.floor_y+track.box.h/2;segment=track.floor_segment
    track.update(incoming,last[0],track.reference,lambda d:dict(y=floor_y,segment=segment))
    assert track.pinball_fast_rebound_active and track.ballistic
    assert track.at(.04).pinball_fast_rebound
    tracker=Tracker(adaptive=True);tracker.pinball_fast_rebound=True
    tracker.update([Detection(Box(100,100,20,20),'pinball',.9),
                    Detection(Box(300,100,20,20),'spider',.9)],1.,(0.,0.),200.)
    assert {t.kind:t.pinball_fast_rebound for t in tracker.tracks}=={'pinball':True,'spider':False}
    assert not Tracker().pinball_fast_rebound and not Track(1,Box(0,0,10,10),'pinball',.9,0.).pinball_fast_rebound
