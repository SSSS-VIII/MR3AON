"""Action history follows own enqueue timing and the state at that time."""
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_action_timing import commit_action
from arena_vision import Box,Perception,advance_player
from arena_mpc import start_action


def standing():
    return dict(time=1.,player=Box(172,204.56,16,37.44),phase='rope_above',jumps=0,
                motion=None,rope=253.,terrain=None,scale_px=40.,stand_w=16.,stand_h=37.44,
                vy=0.,vx=0.,tracks=[])


def test_command_origin_uses_its_device_enqueue_instead_of_the_planning_budget():
    latest=standing();actor=Perception();ack=SimpleNamespace(device_ready_ns=1_100_000_000)
    result=commit_action(actor,latest,'jump',ack)
    assert actor.active_motion['started']==pytest.approx(1.1+1/60)
    assert result['enqueued_time']==1.1
    assert latest['time']==1. and latest['motion']is None


def test_a_landing_between_pixels_and_submission_commits_a_first_jump():
    latest=advance_player(start_action(standing(),'jump1'),.5)
    assert latest['jumps']==1
    actor=Perception();actor.jump_count=1
    result=commit_action(actor,latest,'jump',SimpleNamespace(device_ready_ns=2_000_000_000))
    assert result['committed_phase']=='rope_above'and result['committed_jumps']==0
    assert actor.active_motion['name']=='jump1'and actor.jump_count==1


def test_below_rope_submission_stays_an_up_transfer():
    latest=dict(standing(),phase='rope_below',player=Box(172,264.28,16,37.44))
    actor=Perception()
    commit_action(actor,latest,'jump',SimpleNamespace(device_ready_ns=1_050_000_000))
    assert actor.active_motion['name']=='rope_up'and actor.jump_count==0
