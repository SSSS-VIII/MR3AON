"""Original UI slide: speed cubic, body-parent carry, shrink and recovery."""
import json
from pathlib import Path
import sys
import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_model import PlayerModel

CASES=json.loads((Path(__file__).parent/'fixtures/arena-privileged-slide.json').read_text())


@pytest.mark.parametrize('case',CASES,ids=lambda c:str(c['source_indices']))
def test_original_slide_body_future_including_parent_carry_and_restoration(case):
    before,after=case['before'],case['after'];dt=case['seconds']
    operations=((0.,case['action']),) if case['action']!='none' else ()
    body,motors,valid=PlayerModel(before).trajectory(np.linspace(0,dt,round(dt*120)+1),operations)
    actual=after['role']['colliders'][0]
    assert valid
    assert np.linalg.norm(body[-1,:2]-[actual['center'][a] for a in ('x','y')])<.06
    assert motors[-1].mode==after['state']['physics'].split(':')[0].lower()
    # Shrinking only the sprite would retain the standing capsule's tall core.
    if motors[-1].mode=='slideonground':
        assert body[-1,3]==0
        assert body[-1,2]==pytest.approx(.2,abs=.00001)
    else:
        assert body[-1,3]>.2


def test_slide_current_body_does_not_collapse_back_to_the_ninja_parent_root():
    case=CASES[3];model=PlayerModel(case['before'])
    body,_,_=model.trajectory(np.linspace(0,.1,13))
    expected_offset=case['before']['role']['colliders'][0]['position']['x']-model.initial.x
    assert expected_offset>.5
    assert body[-1,0]>model.initial.x+model.speed*.1+.5


def test_slide_requires_actual_native_duration_and_offset():
    before=json.loads(json.dumps(CASES[0]['before']))
    before['role']['rules'].pop('slide_seconds')
    _,_,valid=PlayerModel(before).trajectory(np.linspace(0,.2,25),((0.,'down'),))
    assert not valid
