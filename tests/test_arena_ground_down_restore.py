"""Ground-down collider restoration before root contact, original pixel labels."""
from pathlib import Path
import json
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
pytest.importorskip('cv2')
import arena_motion as motion
from arena_input_timeline import freeze_pixels,thaw_pixels
from arena_vision import Box,create_motion


def parameters(**extra):
    return dict(height=4.,lead=0.,offset_x=.026,offset_y=0.,width=.4,
                height_box=.936,destination='ground',**extra)


def test_only_ground_collision_geometry_restores_before_root_arrival():
    old=parameters();new=parameters(collider_restore_lead=.02)
    arrival=4/28+motion.transfer_delay('air_down')
    before=arrival-.01
    a=motion.point('air_down',before,old);b=motion.point('air_down',before,new)
    assert a[4]==.2 and b[4]==motion.DATA['stand_height']
    assert a[1:3]==b[1:3]  # Root and vertical child offset do not move.
    assert motion.duration('air_down',old)==motion.duration('air_down',new)
    assert motion.phase('air_down',before,new)=='flip_down'
    assert motion.point('air_down',arrival-.021,new)==motion.point('air_down',arrival-.021,old)
    assert motion.point('air_down',0.,new)==motion.point('air_down',0.,old)
    for destination in ('rope',None):
        a=dict(old,destination=destination);b=dict(new,destination=destination)
        assert motion.point('air_down',before,a)==motion.point('air_down',before,b)


def test_closing_speed_respects_sloping_surface_without_false_early_contact():
    for surface in (-7.,0.,7.):
        old=parameters(surface_velocity=surface);new=dict(old,collider_restore_lead=.02)
        arrival=(4+28*motion.transfer_delay('air_down'))/(28-surface)
        assert motion.point('air_down',arrival-.01,new)[4]==motion.DATA['stand_height']
        assert motion.point('air_down',arrival-.021,new)==motion.point('air_down',arrival-.021,old)
    old=parameters(surface_velocity=29.);new=dict(old,collider_restore_lead=.02)
    assert motion.point('air_down',.1,new)==motion.point('air_down',.1,old)


def test_candidate_is_explicit_and_own_ack_snapshot_preserves_it():
    obs=dict(time=1.,player=Box(180,100,16,37.44),phase='jump1_falling',jumps=1,
             motion=dict(name='jump1',started=.5),rope=300.,scale_px=40.,vy=80.,vx=0.)
    assert 'collider_restore_lead'not in create_motion(obs,'air_down')
    obs['ground_down_collider_restore']=True
    restored=thaw_pixels(freeze_pixels(obs))
    assert create_motion(restored,'air_down')['collider_restore_lead']==.02
    assert obs['jumps']==1 and obs['phase']=='jump1_falling'


def test_both_original_calibrations_keep_under_and_over_estimates_visible():
    fixture=json.loads((Path(__file__).parent/'fixtures/arena-ground-down-restore.json').read_text())
    counts=[]
    for case in fixture['cases']:
        old_under=new_under=old_over=new_over=0
        for row in case['rows']:
            age=row['age']+row['horizon'];old=row['motion'];new=dict(old,collider_restore_lead=.02)
            a=motion.point('air_down',age,old);b=motion.point('air_down',age,new)
            scale=row['stand_h']/motion.DATA['stand_height']
            assert a[4]*scale==pytest.approx(row['legacy_height'])
            assert a[1:3]==b[1:3]
            old_error=a[4]*scale-row['native_height'];new_error=b[4]*scale-row['native_height']
            old_under+=old_error< -4;new_under+=new_error< -4
            old_over+=old_error>4;new_over+=new_error>4
        counts.append((old_under,new_under,old_over,new_over))
    # First run loses its three unsafe 29px underestimates. The holdout also
    # has extra conservative overestimates: do not silently drop those rows.
    assert counts==[(3,0,0,0),(0,0,4,7)]
