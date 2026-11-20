"""Bind original pending item identities and reset geometry before native birth."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import pending_spring

DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-pending-spring.json').read_text())


@pytest.mark.parametrize('case',DATA['cases'],ids=lambda c:c['name'])
def test_original_queued_spring_reset_matches_first_native_trigger(case):
    entry=case['entry'];original=deepcopy(entry)
    item,reason=pending_spring(entry,DATA['template'])
    assert reason is None and entry==original
    assert item['info_identity']==case['after']['info_identity']
    assert item['model_initialized_spawn']
    actual=case['after']['colliders'][0];box=item['colliders'][0]
    for name in ('center','extents','position'):
        assert np.allclose([box[name][a]for a in ('x','y','z')],
            [actual[name][a]for a in ('x','y','z')],atol=.0001,rtol=0)
    assert item['spring']==case['after']['spring']


@pytest.mark.parametrize('change,reason',[
    ('parent','spring_uninstantiated_parent'),
    ('custom','spring_native_info_binding'),
    ('independent','spring_native_info_binding'),
    ('animated','spring_original_prefab_binding'),
    ('script','spring_original_prefab_binding'),
    ('box','spring_original_root_box_binding'),
    ('rotate','spring_unverified_launch_variant'),
    ('continue','spring_unverified_launch_variant'),
    ('jump','spring_unverified_launch_variant'),
    ('direction','spring_unverified_launch_variant'),
    ('speed','spring_native_launch_domain'),
    ('nearest','spring_original_nearest_point_disagrees'),
    ('scale','spring_native_reset_pose_domain'),
])
def test_unvalidated_native_variants_do_not_become_known_pickups(change,reason):
    entry=deepcopy(DATA['cases'][0]['entry']);template=deepcopy(DATA['template'])
    if change=='parent':entry['source']='resolved_uninstantiated_block'
    if change=='custom':entry['custom_type']='ItemBaseDataStruct'
    if change=='independent':entry['info']['independentAnim']=True
    if change=='animated':template['animated_root']=True
    if change=='script':template['root_scripts'].append('UnknownModifier')
    if change=='box':template['colliders'][0]['direct_root']=False
    if change=='rotate':entry['custom']['_needRotate']=True
    if change=='continue':entry['custom']['_continuePop']=True
    if change=='jump':entry['custom']['_jumpLimitTime']=.5
    if change=='direction':entry['info']['_localEulerAngles']['z']=90.
    if change=='speed':entry['custom']['_popSpeed']=float('nan')
    if change=='nearest':entry['info']['<ObjectNearestPosX>k__BackingField']+=1.
    if change=='scale':entry['info']['_localScale']['x']=-1.
    item,actual=pending_spring(entry,template)
    assert item is None and actual==reason


def test_synchronized_removed_item_is_not_recreated_from_level_info():
    entry=deepcopy(DATA['cases'][0]['entry']);entry['sync_blocked']=True
    assert pending_spring(entry,DATA['template'])==(None,'spring_spawn_sync_blocked')
