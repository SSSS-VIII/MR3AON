"""Target contacts are optional benefits, below collision/terrain safety costs."""
import sys
from pathlib import Path
from dataclasses import replace
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Track
from arena_mpc import MpcAvoider
from arena_policy import VisualAvoider


def target(identity=1,x=280,y=90):
    return Track(identity,Box(x,y,20,20),'slice_target',.95,0,observations=4,vx=-500,
        collider_shape='BoxCollider',quad=((x,y),(x+20,y),(x+20,y+20),(x,y+20)))


def observation(tracks,below=False):
    return dict(player=Box(172,270 if below else 211,16,37),phase='rope_below'if below else'rope_above',
        rope=260.,terrain=None,jumps=0,motion=None,time=0.,vy=0,tracks=tracks,scale_px=39.5,
        stand_w=14.2,stand_h=37.,visible_supports=[])


def test_a_reachable_target_above_the_rope_can_motivate_a_jump_without_enemy_detections():
    obs=observation([target()])
    assert VisualAvoider()._objects(obs)==[]
    assert MpcAvoider().uses_search(obs)
    assert MpcAvoider().choose(obs)==('jump','mpc_jump1')


def test_optional_target_reward_cannot_pay_for_colliding_with_an_enemy_at_that_target():
    fruit=target()
    enemy=replace(fruit,id=2,kind='trap')
    assert MpcAvoider().choose(observation([fruit,enemy]))==(None,'mpc_wait')


def test_dense_targets_below_a_ground_entrance_cannot_outweigh_a_terminal_wall_contact():
    obs=observation([target(i+1,240+i,290)for i in range(30)],below=True)
    obs['visible_supports']=[dict(id=1,kind='platform',a=(275,260),b=(640,260),
                                vx=-500,vy=0,stamp=0,confidence=.95)]
    assert MpcAvoider().choose(obs)==('jump','mpc_rope_up')
