"""Source cleanup proof for an already inactive clear-screen object."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_families import skill_issues,retired_clear_screen
from arena_privileged_model import PlayerModel
DATA=json.loads((Path(__file__).parent/'fixtures/arena-privileged-retired-skill.json').read_text())


def test_native_retired_object_is_removed_at_the_next_original_tick():
    before=DATA['before'];after=DATA['after'];original=deepcopy(before)
    assert before['role']['skills']['active'][0]['type']=='SkillClearScreen'
    assert retired_clear_screen(before['role']['skills']['active'][0])
    assert not after['role']['skills']['active']
    assert before['state']['health']==after['state']['health']==5000
    assert not skill_issues(before['role'])and not skill_issues(after['role'])
    assert not any(v.startswith('active_skill:')for v in PlayerModel(before).unsupported)
    assert before==original


@pytest.mark.parametrize('change',['live','hierarchy','collider','callback','coroutine','missing_coroutine',
    'queued_damage','extra_queue','unknown_hook','native','script','different_skill','not_ended','active','source','camera','no_proof'])
def test_no_live_or_unproved_effect_is_removed_from_the_safety_boundary(change):
    role=deepcopy(DATA['before']['role']);row=role['skills']['active'][0];f=row['fields'];d=row['retired_clear_screen']
    if change=='live':d['active_self']=True
    if change=='hierarchy':d['active_hierarchy']=True
    if change=='collider':d['active_colliders']=1
    if change=='callback':d['callbacks_clear']=False
    if change=='coroutine':d['coroutines'][0]['present']=True
    if change=='missing_coroutine':d['coroutines']=[]
    if change=='queued_damage':d['damage_queues']['skillDamageList']=1
    if change=='extra_queue':d['damage_queues']['unknown']=0
    if change=='unknown_hook':d['unknown_hooks']=['SkillClearScreen.SkillEnd']
    if change=='native':d['native_cleanup']=False
    if change=='script':d['component_types'].append('UnknownManagerPoller')
    if change=='different_skill':row['type']='SkillWaterIcePiton'
    if change=='not_ended':f['_bIsSkillEnd']=False
    if change=='active':f['<isActive>k__BackingField']=True
    if change=='source':f['<SkillSource>k__BackingField']='Role: 1'
    if change=='camera':f['_cameraShiftCtrling']=True
    if change=='no_proof':row.pop('retired_clear_screen')
    assert skill_issues(role)==['active_skill:'+row['type']]
