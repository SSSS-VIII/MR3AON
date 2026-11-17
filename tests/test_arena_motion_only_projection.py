"""Own-key bookkeeping must not invoke hazard prediction providers."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from arena_input_timeline import OwnInputTimeline,thaw_pixels
from arena_action_timing import commit_action
from arena_vision import Perception


class Hazard:
    def __init__(self):self.calls=0
    def at(self,seconds):self.calls+=1;return self


def seed():
    f=json.loads((Path(__file__).parent/'fixtures/arena-ground-down-expired-ack.json').read_text())
    state=thaw_pixels(json.dumps(f['receipt']));planned=thaw_pixels(json.dumps(f['planned']))
    actor=Perception();actor.visual_role=True;actor.body_height=state['stand_h']/.73
    actor.jump_count=state['jumps'];actor.active_motion=deepcopy(state['motion'])
    line=OwnInputTimeline(actor);actor.input_timeline=line
    line.before_observe(state['time']);line.after_observe(state)
    return actor,line,state,planned


def test_motion_only_projection_preserves_player_keys_and_cursors():
    actor,line,state,planned=seed();hazard=Hazard();line.latest['tracks']=[hazard]
    at=state['time']+.1
    expected=line.project(at);actual=line.project(at,include_tracks=False)
    assert hazard.calls==1 and expected['tracks']==[hazard]and actual['tracks']==[]
    assert {k:v for k,v in actual.items()if k!='tracks'}=={k:v for k,v in expected.items()if k!='tracks'}
    assert line.consumed==0 and actor.active_motion==state['motion']


def test_real_commit_uses_geometry_replay_without_hazard_forecasts():
    actor,line,state,planned=seed();hazard=Hazard();line.latest['tracks']=[hazard]
    ack=SimpleNamespace(device_ready_ns=round(state['time']*1e9))
    result=commit_action(actor,line.latest,'down',ack,primitive='air_down',planned=planned)
    assert hazard.calls==0
    assert result['committed_primitive']=='air_down'and result['support_unconfirmed']
    assert len(line.events)==1 and line.consumed==0
    assert actor.active_motion==state['motion']
