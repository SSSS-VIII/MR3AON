"""Original collider variants must keep the laser tail inside the warning."""
import pytest

from arena_bamboo_geometry import SOURCE, projectile_envelope
from arena_bamboo_motion import BambooClocks, BambooForecast
from arena_projection import SCALE
from arena_vision import Box


def clocks(enabled):
    result=BambooClocks()
    result.source_geometry_variants=enabled
    result.clocks={1:dict(fire=(1.,1.),confidence=[.95],target_y=180.,
                         lock_count=2,overlap_hypothesis=False,last_seen=.8)}
    return result


@pytest.mark.parametrize('source_scale',[1.,1.3])
@pytest.mark.parametrize('seconds',[0.,.08,.16,.3,.45])
def test_each_original_attack_box_stays_inside_the_same_head_and_tail_envelope(source_scale,seconds):
    g=projectile_envelope()
    predicted=BambooForecast(1,Box(0,180,1,1),'bamboo_forecast',1,0,
        spawn_left=g.spawn_left,spawn_right=g.spawn_right,projectile_width=g.width,
        projectile_height=g.height,velocity_fast=-60*SCALE,velocity_slow=-60*SCALE)
    future=predicted.future(seconds)
    origin=640+2*SCALE-60*SCALE*seconds
    for variant in SOURCE['variants']:
        center=variant['center'];size=variant['size']
        left=origin+(center['x']-size['x']/2)*source_scale*SCALE
        right=origin+(center['x']+size['x']/2)*source_scale*SCALE
        top=180.5+(center['y']-size['y']/2)*source_scale*SCALE
        bottom=180.5+(center['y']+size['y']/2)*source_scale*SCALE
        assert future.x<=left+1e-7
        assert future.x+future.w>=right-1e-7
        assert future.y<=top+1e-7
        assert future.y+future.h>=bottom-1e-7


def test_retention_is_derived_from_tail_clearance_and_preserves_old_default():
    old=clocks(False)
    new=clocks(True)
    assert old.retention_seconds()==.35
    g=projectile_envelope()
    assert g.retention_seconds==pytest.approx((g.spawn_right+g.width/2)/(60*SCALE)+2/60)
    assert .7<g.retention_seconds<.9
    assert not old.forecasts(1.4,0.)
    assert new.forecasts(1.4,0.)
    # No new cue is needed to keep the already observed causal shot alive.
    new.observe([],1.4)
    assert new.clocks
    new.observe([],1.+g.retention_seconds+.001)
    assert not new.clocks


def test_source_geometry_extends_the_tail_without_advancing_the_ordinary_head():
    old=clocks(False).forecasts(1.,0.)[0]
    new=clocks(True).forecasts(1.,0.)[0]
    front=min(v['center']['x']-v['size']['x']/2 for v in SOURCE['variants'])
    assert new.box.x==pytest.approx(640+(2+front*SOURCE['max_scale'])*SCALE)
    assert new.box.x<=old.box.x+1e-4
    assert new.box.x>590  # Widening around the old center would put a fake head near the role.
    assert new.box.x+new.box.w>old.box.x+old.box.w+900
    assert new.projectile_height>old.projectile_height
    assert [v['name'] for v in SOURCE['variants']]==['BambooCtrl','Laser','FlySpear','GoldenBamboo']
    laser=SOURCE['variants'][1]
    assert laser['size']['x']==pytest.approx(23.67)
    assert laser['center']['x']==pytest.approx(9.66)
