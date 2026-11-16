"""Second-jump trajectories at different parent phases, scored on original UI data."""
from pathlib import Path
import sys,json,statistics
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
pytest.importorskip('numpy');pytest.importorskip('cv2')
import arena_motion as motion
from arena_vision import Box,create_motion,native_motion_box,player_future


def observation(age=.55):
    return dict(time=10.,player=Box(180,150,16,37.44),phase='jump1_falling',jumps=1,
        motion=dict(name='jump1',started=10-age),scale_px=40.,stand_w=14.4,stand_h=37.44,
        rope=None,terrain=None,vx=0.,incoming_jump2=True)


def test_second_jump_entry_does_not_teleport_or_shrink_at_zero_time():
    obs=observation();result=native_motion_box(obs,'jump2',0.)
    assert vars(result)==pytest.approx(vars(obs['player']))
    active=create_motion(obs,'jump2');assert active['jump_entry']['parent']is not obs['motion']
    obs['motion']['started']=0.
    assert active['jump_entry']['parent']['started']==9.45


def test_first_jump_fall_continues_before_second_jump_reverses_root():
    active=create_motion(observation(),'jump2')
    assert motion.point('jump2',.015,active)[1]<0
    assert motion.point('jump2',.25,active)[1]>0
    assert motion.apex('jump2',active)==pytest.approx(.03+12.5/34.3)


def test_legacy_or_missing_parent_does_not_claim_a_known_entry_trajectory():
    obs=observation();obs['incoming_jump2']=False
    assert 'jump_entry'not in create_motion(obs,'jump2')
    obs['incoming_jump2']=True;obs['motion']=None
    assert 'jump_entry'not in create_motion(obs,'jump2')


def test_forecasts_reanchor_to_new_observed_body_without_reapplying_past_lead():
    obs=observation();active=create_motion(obs,'jump2');age=.1
    now=dict(obs,time=10+age,motion=active,player=Box(180,120,8,8),phase='jump2_rising')
    result=player_future(now,.05)
    a=motion.point('jump2',age,active);b=motion.point('jump2',age+.05,active)
    assert result.center[1]==pytest.approx(now['player'].center[1]-((b[1]+b[2])-(a[1]+a[2]))*40)


def test_original_ui_falling_entries_improve_on_rising_only_profile_and_holdout():
    cases=json.loads((Path(__file__).parent/'fixtures/arena-jump2-entry.json').read_text())['cases']
    for case in cases:
        assert case['fixed_step']==pytest.approx(.02)
        entry=create_motion(observation(case['parent_age']),'jump2')['jump_entry']
        errors=[abs(motion.jump_entry_root(t,entry)-y)for t,y in case['samples']]
        assert max(errors)<.19  # Original world units; about7.5px, not a no-hit claim.
        if case['intended_delay']>=.3:
            old=[abs(motion.point('jump2',t)[1]-y)for t,y in case['samples']]
            assert statistics.median(errors)<statistics.median(old)*.35
