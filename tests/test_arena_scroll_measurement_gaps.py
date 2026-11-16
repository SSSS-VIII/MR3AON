"""A lost image-pair displacement cannot become zero motion in a speed fit."""
from pathlib import Path
import json
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
pytest.importorskip('numpy')
from arena_support import VisualSupports


def ground(confidence=.4,edge=640.):
    return dict(kind='platform',a=(0.,250.),b=(edge,250.),confidence=confidence,
                left_clipped=True,right_clipped=edge>=628)


def test_constant_speed_with_missing_intervals_never_slows_to_half_speed():
    supports=VisualSupports();t=200000.
    supports.associate([ground()],t)
    for i,measured in enumerate([True,True,True,False,True,False,False,True,True,True],1):
        t=200000.+i*.04
        texture=dict(vx=-800.,dt=.04)if measured else None
        supports.associate([ground()],t,texture)
        assert supports.scroll_vx==pytest.approx(-800.)
        assert (supports.last_translation==t)==measured
        if measured and i in (5,8):assert len(supports.scroll_samples)==2


def test_contiguous_measurements_still_smooth_presented_frame_jitter():
    supports=VisualSupports();t=10.;supports.associate([ground()],t)
    steps=[(.033, -20.),(.033,-40.),(.034,-20.)]*2
    elapsed=position=0.;samples=[]
    for dt,dx in steps:
        if not samples:samples.append((elapsed,position))
        elapsed+=dt;position+=dx;samples.append((elapsed,position))
        supports.associate([ground()],t+elapsed,dict(vx=dx/dt,dt=dt))
    # Least squares of the complete measured displacement chain, independent
    # of the last one-frame velocity. No missing time was bridged here.
    ts=[v[0]for v in samples];xs=[v[1]for v in samples]
    mt=sum(ts)/len(ts);mx=sum(xs)/len(xs)
    expected=sum((a-mt)*(b-mx)for a,b in zip(ts,xs))/sum((a-mt)**2 for a in ts)
    assert supports.scroll_vx==pytest.approx(expected)
    assert abs(supports.scroll_vx-steps[-1][1]/steps[-1][0])>100


def test_intermittent_endpoint_confidence_breaks_the_same_displacement_chain():
    supports=VisualSupports()
    for i,confidence in enumerate([.9,.9,.4,.9,.9,.4,.9,.9]):
        supports.associate([ground(confidence,500.-i*8)],i*.02)
        if i:assert supports.scroll_vx==pytest.approx(-400.)
    assert supports.last_translation==pytest.approx(.14)


def test_original_rooftop_pixels_keep_raw_measurements_without_gap_dilution():
    fixture=json.loads((Path(__file__).parent/'fixtures/arena-scroll-gaps.json').read_text())
    supports=VisualSupports(line_camera_recovery=True,texture_camera_recovery=True)
    for row in fixture['rows']:
        supports.associate(row['segments'],row['time'],row['texture'],camera_prior=row['camera_prior'])
        assert supports.scroll_vx==pytest.approx(row['fixed_velocity'])
        assert (supports.last_translation==row['time'])==row['measured']
    bad=fixture['rows'][56]
    assert bad['legacy_velocity']==pytest.approx(-354.58029688570093)
    assert bad['fixed_velocity']==pytest.approx(bad['texture']['vx'])
    assert abs(bad['fixed_velocity'])>2*abs(bad['legacy_velocity'])
