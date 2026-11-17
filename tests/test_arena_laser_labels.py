"""Original laser marker and collider supervision must survive export."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from arena_bamboo_geometry import retag_laser_targets
from arena_yolo_obb_data import bamboo_marker_quad,collider_quad,visible_quad


def fixture():
    return json.loads((Path(__file__).parent/'fixtures/arena-laser-source-labels.json').read_text())


def profile():
    return dict(separate_bamboo_laser=dict(physical_class=22),
                classes=[{} for _ in range(22)]+[
                    dict(resource='EnemyFlyBamboo',source_part='laser_attack')])


def row_with(collider):
    return dict(objects=[dict(type='EnemyFlyBamboo',dead=False,
                              renderers=[dict(name='X')],colliders=[collider])])


def test_original_laser_marker_excludes_the_long_aim_line():
    renderers=fixture()['marker_renderers']
    quad=bamboo_marker_quad(dict(renderers=renderers))
    assert quad is not None
    assert quad.min(axis=0)==pytest.approx([245.82643508911,240.1188826561])
    assert quad.max(axis=0)==pytest.approx([275.22047042847,267.19717741013])
    assert quad[:,0].max()<300  # The original AimLine extends beyond744.


def test_existing_bamboo_marker_geometry_is_unchanged():
    quad=bamboo_marker_quad(dict(renderers=[
        dict(name='Sprite',box=[180.,200.,190.,210.]),
        dict(name='Triangle (1)',box=[178.,198.,182.,202.]),
        dict(name='AimLine',box=[190.,202.,640.,205.])]))
    assert quad.min(axis=0).tolist()==[178.,198.]
    assert quad.max(axis=0).tolist()==[190.,210.]


def test_native_laser_subtype_changes_class_and_preserves_the_exact_quad():
    collider=fixture()['attack_collider']
    quad=visible_quad(collider_quad(collider))
    assert quad is not None
    untouched=quad+np.array([0.,30.])
    labels=[(18,quad),(4,untouched)]
    result=retag_laser_targets(row_with(collider),labels,profile())
    assert [cls for cls,_ in result]==[22,4]
    assert result[0][1] is quad
    assert result[1][1] is untouched
    # OBB corner order is serialization detail, not a different source box.
    rotated=np.roll(quad[::-1],2,axis=0)
    assert retag_laser_targets(row_with(collider),[(4,rotated)],profile())[0][0]==22


def test_classless_old_profile_and_nonmatching_source_colliders_keep_labels():
    collider=fixture()['attack_collider']
    quad=visible_quad(collider_quad(collider))
    labels=[(18,quad)]
    assert retag_laser_targets(row_with(collider),labels,{}) is labels
    altered=deepcopy(collider)
    altered['center']['x']+=.55  # Prefab position cannot replace Reset geometry.
    assert retag_laser_targets(row_with(altered),labels,profile())[0][0]==18
    altered=deepcopy(collider)
    altered['size']['x']=3.
    assert retag_laser_targets(row_with(altered),labels,profile())[0][0]==18


def test_bad_profile_cannot_retag_a_different_family():
    p=profile()
    p['classes'][22]['resource']='EnemyMace'
    with pytest.raises(ValueError,match='reviewed source collider'):
        retag_laser_targets(row_with(fixture()['attack_collider']),[],p)
