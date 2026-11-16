"""Independent native ledge probes protect freefall and its available jump."""
import json
from pathlib import Path
import sys
import pytest

pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_motion as motion
from arena_vision import Box,advance_player,Perception
from arena_mpc import MpcAvoider
from arena_support import describe_terrain

DATA=json.loads((Path(__file__).parent/'fixtures/arena-walkoff-native.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:f"ledge{c['block']}")
def test_native_ledge_velocity_and_first_jump_are_preserved(case):
    falling=[s for s in case['samples']if s['physics']=='fallFromRun: 13']
    first=falling[0];scale=40.
    obs=dict(time=0.,player=Box(172,100,16,37.44),phase='air_falling',
             rope=None,terrain=None,jumps=0,motion=None,vy=-first['velocity_y']*scale,
             scale_px=scale,tracks=[])
    assert len(falling)==9
    for sample in falling[1:]:
        # Native velocity comes from fixed physics, while the rendered root
        # can still interpolate. Test this derivative against the physics clock.
        dt=(sample['frame']-first['frame'])*DATA['fixed_dt']
        future=advance_player(obs,dt)
        assert future['vy']/scale==pytest.approx(-sample['velocity_y'],abs=1e-5)
        split=advance_player(advance_player(obs,dt*.4),dt*.6)
        assert split['player'].center==pytest.approx(future['player'].center)
    impulse=next(s for s in falling if s['action']=='jump')
    entered=next(s for s in case['samples']if s['frame']>impulse['frame'])
    assert entered['physics']=='jump: 14'and entered['velocity_y']==23.5
    assert MpcAvoider()._options(obs,0.)==[None,'jump1']
    actor=Perception();actor.action('jump',0.,obs)
    assert actor.active_motion['name']=='jump1'and actor.jump_count==1
    assert {s['health']for s in case['samples']}=={5000}


def test_walking_off_supported_floor_uses_the_same_native_freefall():
    # A finite floor ending after .1s; no imaginary support beyond its end.
    segment=dict(id=1,kind='platform',a=(0,260),b=(244,260),vx=-640.,vy=0.,confidence=.95)
    obs=dict(time=0.,player=Box(172,211.28,16,37.44),phase='ground',
             terrain=describe_terrain([segment],segment,180),rope=None,jumps=0,
             motion=None,vy=0.,vx=0.,scale_px=40.,tracks=[])
    future=advance_player(obs,.3)
    assert future['phase']=='air_falling'and future['jumps']==0
    assert future['vy']==pytest.approx(31.5*40*.2)
    assert future['player'].center[1]-obs['player'].center[1]==pytest.approx(.5*31.5*40*.2**2)
    split=advance_player(advance_player(obs,.15),.15)
    assert split['player'].center==pytest.approx(future['player'].center)
    assert split['vy']==pytest.approx(future['vy'])


def test_jump_fall_accelerations_keep_their_distinct_native_values():
    assert motion.air_accelerations(1)==(87.5,31.5)
    assert motion.air_accelerations(2)==pytest.approx((34.3,34.3))
