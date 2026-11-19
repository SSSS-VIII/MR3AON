"""Retimed candidates must earn new native evidence and preserve the owner."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab'))
import retime


def certificate():
    from arena_timing_certificate import schedules
    from arena_input_transport import PROFILE
    def context(full):
        return dict(version=3,transport=dict(PROFILE),passed=True,window_ms=80,offsets_ms=[-40,40],sampling='endpoints',
            clock='Unity.Time.time',timing_reference='each reachable prefix native world-X crossing',
            independent=True,semantic_checks=True,exhaustive=False,scope='whole_board_suffix',
            prefix_coverage='single_adjacent_continuous'if full else'continuous',
            covers_start_frame=0,covers_end_frame=16,operations=2,event_indices=[0,1],
            checks=[dict(passed=True,reason='native_exit',schedule=list(p),actions=[dict(index=i,action=('down','jump')[i],before_physics=('runOnLine: 1','runOnLineDown: 2')[i],transport_action=('down','jump')[i],requested_shift_ms=v,
                actual_shift_ms=v*1.25,nominal_crossing_time=1.,input_time=1.+v*.00125)
                for i,v in enumerate(p)])for p in sorted(schedules(2,full))])
    return dict(context(True),reentries=[dict(seed=i,fresh_initialization=True,unprotected=True,
                                             validation=context(False))for i in(1,2)])


def state(tick):
    return dict(episodeFrame=tick, health=5000, position=dict(x=tick/2), physics='runOnLine: 1')


def board(tick):
    return dict(map=42, stage_index=int(tick>=16), stage_id=50022 if tick<16 else 50031,
                stage_start=0, mounted=False)


def source():
    return dict(complete=True, uses_restart_replay=False, initial_ram_root=dict(result=dict(id=1)),
        start=dict(state=state(0), board=board(0), health=5000),
        end=dict(state=state(16), board=board(16)), timing_validation=certificate(),
        route=[dict(action={4:'down',10:'jump'}.get(t,'none'), ticks=2, board=board(t+2),
                    job=dict(before=state(t), after=state(t+2), done=True)) for t in range(0,16,2)])


class Gate:
    def __init__(self):
        self.points={1:state(0), 2:state(50)}
        self.current=state(50)
        self.serial=2
        self.inputs=[]
    def snapshot(self):
        self.serial+=1; self.points[self.serial]=deepcopy(self.current)
        return dict(result=dict(id=self.serial))
    def restore(self, point):
        self.current=deepcopy(self.points[point]); return dict(ms=1)
    def drop(self, point): del self.points[point]
    def call(self, op, **_):
        return deepcopy(self.current) if op=='state' else board(self.current['episodeFrame'])
    def step(self, ticks, action):
        before=deepcopy(self.current)
        self.inputs.append((before['episodeFrame'], action))
        self.current=state(before['episodeFrame']+ticks)
        return dict(before=before, after=deepcopy(self.current), done=True)


def test_plan_moves_one_input_without_moving_other_boundaries_or_mutating_source():
    original=source(); copied=deepcopy(original)
    result=retime.plan(original,0,2)
    assert original==copied
    assert [(r['job']['before']['episodeFrame'],r['action']) for r in result if r['action']!='none']==[(6,'down'),(10,'jump')]
    for a,b in zip(result,original['route']):
        assert a['job']==b['job'] and a['ticks']==b['ticks']


@pytest.mark.parametrize('event,shift', [(0,1),(0,6),(0,8),(1,-6),(2,2),(0,0)])
def test_plan_rejects_missing_boundaries_and_changed_input_order(event,shift):
    with pytest.raises(ValueError):retime.plan(source(),event,shift)


def test_candidate_reexecutes_then_recertifies_all_inputs_and_restores_owner(tmp_path,monkeypatch):
    gate=Gate(); original=deepcopy(gate.points)
    path=tmp_path/'source.json'; path.write_text(json.dumps(source()))
    calls=[]
    def verify(gate, rows, **kwargs):
        calls.append(kwargs)
        assert kwargs['whole_board'] and all(r['point'] in gate.points for r in rows)
        assert [t for t,a in gate.inputs if a!='none']==[6,10]
        return certificate()
    monkeypatch.setattr(retime,'verify',verify)
    result=retime.run(gate,path,tmp_path/'candidate',event_index=0,shift_ticks=2)
    assert result['complete'] and result['no_health_loss'] and len(calls)==1
    assert gate.points==original and gate.current==state(50)
    assert all('point' not in r for r in result['route'])
    assert json.loads(path.read_text())==source()


def test_failed_tolerance_never_inherits_the_source_certificate(tmp_path,monkeypatch):
    gate=Gate(); path=tmp_path/'source.json'; path.write_text(json.dumps(source()))
    monkeypatch.setattr(retime,'verify',lambda *a,**k:dict(passed=False))
    result=retime.run(gate,path,tmp_path/'candidate',event_index=0,shift_ticks=2)
    assert not result['complete'] and result['timing_validation']==dict(passed=False)
    assert gate.current==state(50) and set(gate.points)=={1,2}


def test_retired_checkpoint_or_wrong_entry_cannot_start_a_candidate(tmp_path):
    gate=Gate(); path=tmp_path/'source.json'; path.write_text(json.dumps(source()))
    del gate.points[1]
    with pytest.raises(ValueError):
        retime.run(gate,path,tmp_path/'missing',event_index=0,shift_ticks=2)
    assert not (tmp_path/'missing').exists()
    gate.points[1]=state(2)
    with pytest.raises(RuntimeError):
        retime.run(gate,path,tmp_path/'wrong',event_index=0,shift_ticks=2)
    assert gate.current==state(50) and set(gate.points)=={1,2}


def test_uncertain_owner_restore_keeps_recovery_points(tmp_path,monkeypatch):
    gate=Gate(); path=tmp_path/'source.json'; path.write_text(json.dumps(source()))
    original=gate.restore
    def restore(point):
        if point==3:raise TimeoutError('restore uncertain')
        return original(point)
    monkeypatch.setattr(gate,'restore',restore)
    monkeypatch.setattr(retime,'verify',lambda *a,**k:dict(passed=False))
    with pytest.raises(TimeoutError):
        retime.run(gate,path,tmp_path/'candidate',event_index=0,shift_ticks=2)
    assert {1,2,3} <= set(gate.points)
    assert 'owner_restore_error' in json.loads((tmp_path/'candidate/report.json').read_text())
