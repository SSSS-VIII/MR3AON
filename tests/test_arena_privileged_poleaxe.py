"""Original dual-direction axe phases and whole damage-volume containment."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from arena_privileged_model import PlayerModel,hazard_forecasts
from arena_privileged_poleaxe import checked_entry,forecast,carry_ratio,adjusted_bone
from arena_spine_geometry import full_scale_follow_quad

FIXTURE=json.loads((ROOT/'tests/fixtures/arena-privileged-poleaxe.json').read_text())


@pytest.mark.parametrize('case',FIXTURE['cases'])
def test_original_living_ready_attack_and_direction_pairs_are_contained(case):
    before=case['before'];after=case['after'];elapsed=after['state']['time']-before['state']['time']
    model=PlayerModel(before);assert not model.unsupported
    assert before['state']['health']==after['state']['health']==5000
    times=np.linspace(0,elapsed,round(elapsed*120)+1)
    hazards,missing=hazard_forecasts(before,times,model)
    assert not missing and len(hazards)==2
    actual={c['id']:c for c in after['enemy']['colliders']if c.get('damage_kind')}
    for h in hazards:
        c=actual[h.id]
        position=np.array([c['center'][a]for a in ('x','y')]);extent=np.array([c['extents'][a]for a in ('x','y')])
        assert np.all(abs(position-h.centers[-1])+extent<=h.extents[-1]+h.padding+1e-6)
        assert h.active[-1] and h.approximate
    # Reconstruct the observed original quad independently of future clocks.
    enemy=before['enemies'][0];spine=enemy['spine'];bone=next(b for b in spine['bones']if b['name']=='axe')
    weapon=next(c for c in enemy['colliders']if c.get('spine_follow'))
    quad=full_scale_follow_quad(spine,bone,weapon)
    original=np.array([[p['x'],p['y']]for p in weapon['quad']])
    assert abs(quad-original).max()<.0001


@pytest.mark.parametrize('change,reason',[
    ('mix','poleaxe_mixed_queued_or_modified_track'),
    ('queue','poleaxe_mixed_queued_or_modified_track'),
    ('callback','poleaxe_mixed_queued_or_modified_track'),
    ('clock','poleaxe_spine_clock_or_callbacks'),
    ('skin','poleaxe_original_spine_missing'),
    ('pose','poleaxe_current_pose_disagrees_with_cache'),
    ('moving','poleaxe_moving_root'),
    ('chain','Unvalidated full-scale native bone-follow chain'),
    ('scale','Unvalidated full-scale native bone-follow configuration'),
    ('player','poleaxe_player_trajectory_unsupported'),
])
def test_unvalidated_native_states_are_rejected_instead_of_using_body_only(change,reason):
    sample=deepcopy(next(c for c in FIXTURE['cases']if c['before']['enemies'][0]['fields']['_enemyState']=='Idle: 0'))
    before=sample['before'];e=before['enemies'][0];entry=e['spine']['tracks'][0]['entry']
    weapon=next(c for c in e['colliders']if c.get('spine_follow'))
    if change=='mix':entry['mixDuration']=.2
    if change=='queue':entry['has_next']=True
    if change=='callback':entry['callbacks']={'Complete':[{'method':'unmodelled'}]}
    if change=='clock':e['spine']['time_scale']=2
    if change=='skin':e['spine']['skin']='default'
    if change=='pose':next(b for b in e['spine']['bones']if b['name']=='axe')['x']+=1
    if change=='moving':e['fields']['currMoveVelocity']['x']=1
    if change=='chain':weapon['spine_follow']['full_scale_chain']=False
    if change=='scale':weapon['spine_follow']['chain'][0]['fields']['scale']=False
    model=PlayerModel(before)
    if change=='player':model.unsupported.append('role:pop')
    result,missing=forecast(e,np.linspace(0,.5,61),before,model)
    assert result is None and missing==reason


def test_full_original_clip_extremes_are_not_a_static_body_forecast():
    before=deepcopy(FIXTURE['cases'][0]['before']);model=PlayerModel(before);times=np.linspace(0,1.8,217)
    e=before['enemies'][0];data,_,entry,_=checked_entry(e)
    result,missing=forecast(e,times,before,model)
    assert not missing
    weapon=next(c for c in e['colliders']if c.get('spine_follow'))
    centers,extents=result[4][weapon['id']]
    assert np.ptp(centers[:,1])+np.ptp(extents[:,1])>.5
    assert data['tick']==pytest.approx(.02)
    assert entry['mixDuration']==0


def test_candidate_slide_changes_the_original_distance_trigger_forecast():
    before=deepcopy(FIXTURE['cases'][0]['before']);enemy=before['enemies'][0]
    model=PlayerModel(before);times=np.linspace(0,1.8,217)
    _,coast,_=model.trajectory(times)
    _,slide,valid=model.trajectory(times,((.05,'down'),))
    assert valid
    baseline,why=forecast(enemy,times,before,model,coast);assert not why
    changed,why=forecast(enemy,times,before,model,slide);assert not why
    weapon=next(c for c in enemy['colliders']if c.get('spine_follow'))
    # The original slide offsets RoleObj and reaches the attack threshold
    # sooner. Reusing one coast forecast for every candidate is incorrect.
    assert abs(baseline[4][weapon['id']][0]-changed[4][weapon['id']][0]).max()>.5


def test_original_pooled_ready_retains_its_unkeyed_parent_scale():
    before=next(c['before']for c in FIXTURE['cases']if c.get('pooled_scale'))
    e=before['enemies'][0];data,spine,entry,index=checked_entry(e)
    clip=data['animations'][entry['animation']]
    assert clip['keyed_properties']['axe2']==['RotateTimeline','TranslateTimeline']
    ratio=carry_ratio(spine,clip,index)
    assert ratio[0]==pytest.approx(.982,abs=1e-6)
    original=next(b for b in spine['bones']if b['name']=='axe')
    cached=clip['samples'][index]['bone']
    corrected=adjusted_bone(clip['samples'][index],ratio)
    assert abs(cached['x']-original['x'])>.08
    assert max(abs(corrected[k]-original[k])for k in ('x','y','a','b','c','d'))<.000002
