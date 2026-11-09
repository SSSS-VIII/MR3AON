import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_obb_replay import observe_own_input,state_family


def test_recorded_key_is_replayed_at_previous_frame_time_using_only_visual_state():
    class Actor:
        last_observation=dict(phase='ground')
        def __init__(self):self.received=[]
        def action(self,*args):self.received.append(('key',*args))
        def observe(self,*args):self.received.append(('pixels',*args));return self.last_observation
    actor=Actor();pixels=object()
    assert observe_own_input(actor,pixels,1.06,1.,'down')==dict(phase='ground')
    assert actor.received==[('key','slide',1.),('pixels',pixels,1.06)]
    actor.last_observation=dict(phase='rope_above');actor.received=[]
    observe_own_input(actor,pixels,1.12,1.06,'down')
    assert actor.received[0]==('key','down',1.06)


def test_first_frame_has_no_fabricated_key_and_jump_count_families_stay_distinct():
    class Actor:
        last_observation=None
        def action(self,*a):pytest.fail('unrecorded first-frame key')
        def observe(self,*a):return'done'
    assert observe_own_input(Actor(),object(),0,None,'jump')=='done'
    assert state_family('jump1_falling')=='jump1'
    assert state_family('jump2_rising')=='jump2'
    assert state_family('flip_down')=='transition'
