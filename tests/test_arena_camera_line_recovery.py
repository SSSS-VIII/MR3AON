"""Camera translation remains observable when a detector changes segmentation."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
pytest.importorskip('numpy')
from arena_support import VisualSupports,overlapping_static_camera_shift


def line(x1,x2,y,*,stamp=1.,slope=0.,kind='rope',confidence=.95):
    return dict(a=(x1,y+slope*x1),b=(x2,y+slope*x2),kind=kind,
                confidence=confidence,stamp=stamp)


@pytest.mark.parametrize('dy',[-22.,15.])
def test_split_merge_recovers_camera_without_identity_or_horizontal_speed(dy):
    old=[line(0,310,220),line(300,640,220)]
    merged=[line(40,610,220+dy,stamp=1.04)]
    assert overlapping_static_camera_shift(merged,old)==pytest.approx(dy)
    split=[line(0,280,220+dy+8,stamp=1.08),line(270,640,220+dy+8,stamp=1.08)]
    assert overlapping_static_camera_shift(split,merged)==pytest.approx(8.)


def test_scrolling_slope_subtracts_material_translation_before_camera():
    old=[line(0,320,100,slope=.3,kind='platform'),line(310,640,100,slope=.3,kind='platform')]
    dx=-30.;dy=12.
    new=[line(0,610,100+dy-.3*dx,stamp=1.04,slope=.3,kind='platform')]
    assert overlapping_static_camera_shift(new,old,dx)==pytest.approx(dy)
    assert overlapping_static_camera_shift(new,old) is None


@pytest.mark.parametrize('change',[dict(kind='floating_platform'),dict(confidence=.6),dict(stamp=1.3),dict(slope=.1)])
def test_unproven_material_is_not_camera_evidence(change):
    new=line(0,640,232,stamp=1.04);new.update(change)
    if 'slope'in change:new=line(0,640,232,stamp=1.04,slope=change['slope'])
    assert overlapping_static_camera_shift([new],[line(0,640,220)]) is None


def test_parallel_levels_are_ambiguous_not_two_votes_for_nearest():
    old=[line(0,640,210),line(0,640,230)]
    assert overlapping_static_camera_shift([line(0,640,220,stamp=1.04)],old) is None


def test_short_or_disjoint_segments_do_not_prove_common_material():
    assert overlapping_static_camera_shift([line(0,80,220,stamp=1.04)],[line(0,80,220)]) is None
    assert overlapping_static_camera_shift([line(400,640,220,stamp=1.04)],[line(0,240,220)]) is None


def test_recovery_is_opt_in_and_tracks_can_restart():
    plain=VisualSupports();fixed=VisualSupports(line_camera_recovery=True)
    sequence=[(1.,[line(-3,423,241.25),line(388,626,240.875)]),
              (1.04,[line(52,623,235.89)]),(1.08,[line(-3,282,219.5),line(275,645,219.625)])]
    for stamp,segments in sequence:
        a=plain.associate(segments,stamp);b=fixed.associate(segments,stamp)
    assert [s['id']for s in a]==[s['id']for s in b]
    assert plain.camera_y==0.
    assert fixed.camera_y==pytest.approx(-21.625,abs=.5)
    assert fixed.camera_motion_source=='support_line_overlap'
