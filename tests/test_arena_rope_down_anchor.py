"""Pixel endpoint forecasts checked against independent original UI motion."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Perception,player_future,advance_player
from arena_rope_transfer import anchored_down_future
from arena_input_timeline import freeze_pixels,thaw_pixels

DATA=json.loads((Path(__file__).parent/'fixtures/arena-rope-down-anchor.json').read_text())


def state(case=0):
    obs=deepcopy(DATA['cases'][case]['input']);obs['player']=Box(**obs['player'])
    return obs


@pytest.mark.parametrize('index',range(3))
def test_current_compact_pixels_reach_original_rope_side_instead_of_a_shifted_profile_endpoint(index):
    case=DATA['cases'][index];obs=state(index);before=deepcopy(obs)
    assert player_future(obs,case['horizon']).center[1]==pytest.approx(case['old_center_y'])
    result=player_future(dict(obs,rope_down_anchor=True),case['horizon'])
    assert vars(result)==pytest.approx(case['prototype'])
    assert abs(result.center[1]-case['expected_native_only']['center_y'])<.5
    assert result.h==pytest.approx(obs['stand_h'])
    assert obs==before and obs['jumps']==1 and obs['phase']=='flip_down'


def test_default_perception_keeps_existing_profile_and_timeline_keeps_explicit_candidate():
    assert Perception().rope_down_anchor is False
    obs=dict(state(),rope_down_anchor=True)
    restored=thaw_pixels(freeze_pixels(obs))
    assert restored['rope_down_anchor'] is True
    assert player_future(restored,.2)==player_future(obs,.2)


@pytest.mark.parametrize('change',[
    {'rope':None},{'motion':None},
    {'motion.name':'air_up'},{'motion.name':'rope_down'},{'motion.name':'jump1'},
    {'motion.destination':'ground'},{'motion.contact_pending':True},
    {'motion.support_unconfirmed':True},
])
def test_other_actions_missing_rope_and_unconfirmed_pending_targets_keep_existing_path(change):
    obs=state()
    for key,value in change.items():
        if key.startswith('motion.'):obs['motion'][key.split('.')[1]]=value
        else:obs[key]=value
    assert anchored_down_future(obs,.2)is None


@pytest.mark.parametrize('change',[
    {'scale_px':float('nan')},{'scale_px':0.},{'stand_h':float('inf')},
    {'vx':float('inf')},{'motion.speed':-28.},
])
def test_invalid_or_opposite_motion_never_creates_an_endpoint(change):
    obs=state()
    for key,value in change.items():
        if key.startswith('motion.'):obs['motion'][key.split('.')[1]]=value
        else:obs[key]=value
    assert anchored_down_future(obs,.2)is None


def test_before_key_delay_or_noncompact_airborne_body_is_not_reanchored():
    obs=state();obs['time']=obs['motion']['started']+.001
    assert anchored_down_future(obs,.2)is None
    obs=state();obs['player']=Box(180,100,16,37)
    assert anchored_down_future(obs,.2)is None


def test_finite_rope_end_cannot_be_extended_to_an_unseen_future_landing():
    obs=state();seg=obs['rope_segment'];obs['rope_segments']=[seg]
    seg.update(a=[0.,260.],b=[200.,260.],vx=-800.,vy=0.,right_clipped=False)
    assert anchored_down_future(obs,.2)is None


def test_forecast_geometry_does_not_acknowledge_observed_contact_or_replenish_jump_budget():
    obs=dict(state(),rope_down_anchor=True);before=deepcopy(obs)
    result=advance_player(obs,.2)
    assert obs==before
    assert result['jumps']==obs['jumps']
    assert not result.get('rope_contact_observed')
    assert result['motion']['requires_contact']


def test_zero_horizon_and_nonintersecting_past_target_preserve_the_measured_body():
    obs=state();assert anchored_down_future(obs,0)==obs['player']
    target=obs['rope']+.75*obs['scale_px'];p=obs['player']
    obs['player']=Box(p.x,target+10,p.w,p.h)
    result=anchored_down_future(obs,.04)
    assert result.center[1]>obs['player'].center[1]
    assert result.h==p.h  # The separate, rejected pending clamp stays disabled.


def test_a_predicted_arrival_stays_on_its_visible_surface_until_ledger_duration_ends():
    obs=state();seg=obs['rope_segment'];seg['a'][1]=seg['b'][1]=obs['rope'];seg['vy']=0.
    obs['rope_segments']=[seg];arrived=anchored_down_future(obs,.2)
    at=dict(obs,player=arrived,time=obs['time']+.2)
    result=anchored_down_future(at,.04)
    assert vars(result)==pytest.approx(vars(Box(arrived.x+at['vx']*.04,arrived.y,arrived.w,arrived.h)))
