"""Pending visual acknowledgement must not remove native rope clamping."""
from pathlib import Path
import sys,json
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,advance_player,player_future

FIXTURE=json.loads((Path(__file__).parent/'fixtures/arena-pending-rope-contact.json').read_text())


def frozen_state():
    state=json.loads(json.dumps(FIXTURE['state']));state['player']=Box(**state['player']);state['tracks']=[];state['pending_rope_clamp']=True
    return state


def test_native_collision_body_is_not_extrapolated_forty_nine_pixels_below_upper_rope():
    state=frozen_state();truth=FIXTURE['expected']
    assert abs(truth['alignment_ms'])<2.
    assert state['motion']['contact_pending']and state['player'].h<9.
    future=advance_player(state,truth['horizon'])
    assert future['player'].center[1]==pytest.approx(truth['native_body_center_y'],abs=.1)
    assert future['player'].h==state['stand_h']
    # Forecast geometry is not an acknowledgement of native action completion.
    assert future['phase']=='flip_up'and future['jumps']==state['jumps']==1
    assert future['motion']['contact_pending']
    assert not future.get('rope_contact_observed',False)


@pytest.mark.parametrize('name,speed,target,center',[
    ('air_up',28.,230.,234.),
    ('air_up',-8.,230.,226.),
    ('air_down',28.,290.,294.),
    ('rope_down',8.,290.,294.),
    ('rope_up',-8.,230.,226.),
])
def test_each_original_rope_side_clamps_after_pixel_overshoot_without_resetting_jumps(name,speed,target,center):
    state=dict(time=1.,player=Box(176,center-4,8,8),phase='flip_up'if 'up'in name else'flip_down',
               jumps=2,tracks=[],pending_rope_clamp=True,rope=260.,terrain=None,scale_px=40.,stand_w=16.,stand_h=37.44,
               motion=dict(name=name,started=0.,contact_pending=True,requires_contact=True,destination='rope',speed=speed,
                           height=0.,lead=0.,offset_x=0.,offset_y=0.,width=.2,height_box=.2))
    after=advance_player(state,.08)
    assert after['player'].center[1]==target
    assert after['player'].h==37.44
    assert after['motion']is not None and after['jumps']==2
    split=advance_player(advance_player(state,.04),.04)
    assert split['player']==after['player']


@pytest.mark.parametrize('unknown',[False,True])
def test_missing_finite_rope_or_unconfirmed_target_cannot_snap_body_back(unknown):
    state=frozen_state();state['player']=Box(176,230,8,8)
    if unknown:state['motion']['support_unconfirmed']=True
    else:
        segment=state['rope_segment'];segment['b']=[170.,259.]
        state['rope_segments']=[segment];state['rope']=None
    after=player_future(state,.04)
    assert after.h==8.
    assert after.center[1]>state['player'].center[1]+40.


def test_unverified_candidate_stays_disabled_and_input_history_keeps_its_value():
    from arena_vision import Perception
    from arena_input_timeline import freeze_pixels,thaw_pixels
    assert not Perception().pending_rope_clamp
    state=frozen_state();old=dict(state,pending_rope_clamp=False)
    future=player_future(old,.04)
    assert future.center[1]-FIXTURE['expected']['native_body_center_y']>48.
    assert thaw_pixels(freeze_pixels(state))['pending_rope_clamp']is True
    assert thaw_pixels(freeze_pixels(old))['pending_rope_clamp']is False
