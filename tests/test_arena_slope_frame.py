"""Slope progression must not be counted as camera motion in enemy tracks."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_support import VisualSupports,height,describe_terrain
from arena_vision import Box,Detection,Tracker,player_future,cap_landing,advance_player


@pytest.mark.parametrize('slope',[-.5,.5])
@pytest.mark.parametrize('camera_vy',[0.,80.])
def test_static_enemy_and_running_role_have_one_relative_slope_motion(slope,camera_vy):
    supports=VisualSupports();tracker=Tracker(adaptive=True)
    for i in range(12):
        t=i*.025;shift=-300*t;camera=camera_vy*t
        a=(20+shift,260+camera);b=(620+shift,260+600*slope+camera)
        surface=260+slope*(180-a[0])+camera
        p=Box(172,surface-48.72,16,37.44)
        support=supports.observe([dict(kind='platform',a=a,b=b,confidence=.95)],p,t)
        tracks=tracker.update([Detection(Box(400+shift,210+camera,20,20),'trap',.95)],t,
                              support['tracking_reference'],surface)
    obs=dict(player=p,phase='ground',terrain=support['terrain'],rope=None,scale_px=40.,
             time=t,jumps=0,motion=None,vy=0)
    assert tracker.tracks[0].vy==pytest.approx(0,abs=1e-7)
    assert support['camera_vy']==pytest.approx(camera_vy,abs=1e-6)
    future=player_future(obs,.2);enemy=tracks[0].future(.2)
    assert future.center[1]-p.center[1]==pytest.approx(60*slope,abs=1e-6)
    assert enemy.center[1]==pytest.approx(tracks[0].box.center[1],abs=1e-6)


def test_rope_running_and_jump_landing_follow_visible_sloping_line():
    segment=dict(id=1,kind='rope',a=(0,350),b=(640,30),vx=-200.,vy=0.)
    p=Box(172,211.28,16,37.44)
    obs=dict(player=p,phase='rope_above',rope=260.,rope_segment=segment,terrain=None,
             time=0,jumps=0,motion=None,vy=0,scale_px=40.,stand_w=16,stand_h=37.44)
    assert player_future(obs,.2).center[1]==pytest.approx(p.center[1]-20)
    landed=cap_landing(obs,Box(172,300,16,37.44),.8,'jump1',forecast_seconds=.2)
    assert landed.center[1]==pytest.approx(210)
    predicted=advance_player(obs,.2)
    assert predicted['rope']==pytest.approx(240)


def test_connected_slope_transition_is_followed_but_gap_still_falls():
    flat=dict(id=1,kind='platform',a=(0,260),b=(220,260),vx=-200.,vy=0.)
    slope=dict(id=2,kind='platform',a=(220,260),b=(640,50),vx=-200.,vy=0.)
    p=Box(172,211.28,16,37.44)
    obs=dict(player=p,phase='ground',rope=None,terrain=describe_terrain([flat,slope],flat,180),
             time=0,jumps=0,motion=None,vy=0,scale_px=40.)
    predicted=advance_player(obs,.4)
    assert predicted['player'].center[1]==pytest.approx(p.center[1]-20)
    assert predicted['terrain']['selected_id']==2
    gap=dict(slope,a=(260,260))
    fallen=player_future(dict(obs,terrain=describe_terrain([flat,gap],flat,180)),.4)
    assert fallen.center[1]>p.center[1]+20


def test_floating_surface_motion_cannot_be_used_as_the_camera_reference():
    supports=VisualSupports()
    for i in range(6):
        t=i*.025
        result=supports.observe([dict(kind='platform',a=(20-200*t,260),b=(600-200*t,260),confidence=.9),
            dict(kind='floating_platform',a=(250-200*t,200-50*t),b=(350-200*t,200-50*t),confidence=.9)],
            Box(172,210,16,40),t)
    assert result['camera_vy']==pytest.approx(0)
    floating=next(s for s in result['segments']if s['kind']=='floating_platform')
    assert floating['vy']==pytest.approx(-50)


def test_free_fall_retiming_advances_velocity_instead_of_restarting_gravity():
    obs=dict(player=Box(172,100,16,37),phase='air_falling',rope=None,terrain=None,
             time=0,jumps=0,motion=None,vy=50.,scale_px=40.)
    direct=advance_player(obs,.2)
    split=advance_player(advance_player(obs,.08),.12)
    assert split['player'].center==pytest.approx(direct['player'].center)
    assert split['vy']==pytest.approx(direct['vy'])


def test_slope_forecast_includes_runner_horizontal_drift_against_scroll():
    segment=dict(id=1,kind='platform',a=(0,350),b=(640,30),vx=-500.,vy=0.)
    obs=dict(player=Box(172,211.28,16,37.44),phase='ground',rope=None,
             terrain=describe_terrain([segment],segment,180),time=0,jumps=0,motion=None,
             vy=0,scale_px=40.,vx=-200.)
    future=player_future(obs,.1)
    assert future.center[0]==pytest.approx(160)
    assert future.center[1]-obs['player'].center[1]==pytest.approx(-15)
