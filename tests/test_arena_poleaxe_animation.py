"""Original-engine collider geometry protects the static animation prior."""
from pathlib import Path
import json
import sys
import pytest
np=pytest.importorskip('numpy')

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_poleaxe_animation import PoleaxeAnimation

FIXTURE=json.loads((Path(__file__).parent/'fixtures/arena-poleaxe-animation-native.json').read_text())


@pytest.mark.parametrize('sample',FIXTURE['samples'])
def test_original_up_and_down_weapon_colliders_match_native_projection(sample):
    prior=PoleaxeAnimation()
    quad=prior.quad(sample['clip'],sample['phase'],origin=sample['origin'],
                    pixels_per_world=sample['pixels_per_world'],screen=True)
    # Unity forms world corners in float32 before projecting them. At these
    # map coordinates one world ULP is already a fraction of a screen pixel.
    world_ulp=float(np.spacing(np.float32(max(map(abs,sample['world_root'])))))
    bound=4*world_ulp*sample['pixels_per_world']+.0002
    assert bound<.03
    np.testing.assert_allclose(quad,sample['quad'],atol=bound,rtol=0)


def test_world_and_screen_coordinates_share_the_same_original_geometry():
    prior=PoleaxeAnimation();world=prior.quad('attack_down',.4)
    screen=prior.quad('attack_down',.4,origin=(200,120),pixels_per_world=40,screen=True)
    np.testing.assert_allclose(screen,world*[40,-40]+[200,120],atol=1e-10)


@pytest.mark.parametrize('clip',['attack_up','attack_down'])
def test_batched_original_poses_match_native_projection(clip):
    samples=[s for s in FIXTURE['samples']if s['clip']==clip];prior=PoleaxeAnimation()
    quads=prior.quads(clip,[s['phase']for s in samples],origins=[s['origin']for s in samples],
                      pixels_per_world=samples[0]['pixels_per_world'],screen=True)
    for q,sample in zip(quads,samples):
        ulp=float(np.spacing(np.float32(max(map(abs,sample['world_root'])))))
        np.testing.assert_allclose(q,sample['quad'],atol=4*ulp*sample['pixels_per_world']+.0002,rtol=0)


def test_one_shot_attack_holds_final_pose_and_ready_curves_remain_nominal():
    prior=PoleaxeAnimation();duration=prior.clips['attack_up'][0]['duration']
    np.testing.assert_array_equal(prior.pose('attack_up',duration+1),prior.pose('attack_up',duration))
    np.testing.assert_array_equal(prior.pose('attack_up',-1),prior.pose('attack_up',0))
    assert prior.clips['attack_down_ready'][0]['setup_pose_only']
    assert not prior.clips['attack_down'][0]['setup_pose_only']


@pytest.mark.parametrize('phase',[float('nan'),float('inf'),-float('inf')])
def test_nonfinite_animation_clock_is_rejected(phase):
    with pytest.raises(ValueError,match='finite'):
        PoleaxeAnimation().pose('attack_up',phase)


def test_invalid_source_time_axis_is_rejected(tmp_path):
    data=PoleaxeAnimation().data
    data['clips']['attack_up']['samples'][2][0]=data['clips']['attack_up']['samples'][1][0]
    path=tmp_path/'invalid.json';path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='samples'):
        PoleaxeAnimation(path)
