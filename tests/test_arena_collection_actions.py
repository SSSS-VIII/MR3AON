import random
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_collection_actions import choose_action


def scene():
    return dict(t=1,physics='runOnGround: 5',support_id=42,role=dict(point=dict(x=180,y=220)),
                supports=[dict(id=42,kind='platform',start=dict(x=0,y=259),finish=dict(x=220,y=259))])


def test_collection_exploration_jumps_before_missing_support_and_keeps_native_input_cooldown():
    row=scene()
    assert choose_action(row,random.Random(1),0)==('jump','native_support_edge')
    assert choose_action(row,random.Random(1),.9)==('none','cooldown')
    row['physics']='runOnLineDown: 2'
    assert choose_action(row,random.Random(1),0)==('down','native_support_edge')


def test_contiguous_original_support_does_not_create_a_fictitious_gap():
    row=scene();row['supports'].append(dict(id=43,kind='rope',start=dict(x=220,y=259),finish=dict(x=800,y=259)))
    assert choose_action(row,random.Random(1),0)==('none','idle')
    row['supports'][-1]['hidden']=True
    assert choose_action(row,random.Random(1),0)==('jump','native_support_edge')


def test_dataset_double_jump_uses_actual_floating_support_and_not_the_dead_floor():
    row=scene();row['physics']='fall: 15';row['role']['point']['y']=220
    row['supports'].append(dict(id=43,kind='platform',floating=True,start=dict(x=450,y=250),finish=dict(x=600,y=250)))
    assert choose_action(row,random.Random(1),0)==('jump','native_floating_approach_double_jump')
    row['physics']='fall2: 17'
    assert choose_action(row,random.Random(1),0)==('none','idle')
